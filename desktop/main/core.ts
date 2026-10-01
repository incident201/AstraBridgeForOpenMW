import {access,copyFile,cp,mkdir,open,readFile,rename,rm,stat,writeFile} from 'node:fs/promises';
import {basename,dirname,join,resolve} from 'node:path';
import {homedir} from 'node:os';
import {randomBytes,randomUUID} from 'node:crypto';
import {Readable} from 'node:stream';
import {pipeline} from 'node:stream/promises';
import {createWriteStream} from 'node:fs';
import * as tar from 'tar';
import {PodmanBackend} from './runtime/PodmanBackend';
import {WslContainerBackend} from './runtime/WslContainerBackend';
import type {Progress,RuntimeBackend,RuntimeSpec} from './runtime/RuntimeBackend';

export interface Release {version:string; image:string; digest:string; development?:boolean; runtime_api:number; game_api:number}
export interface Installation extends RuntimeSpec {
  installed:boolean; storageDirectory:string; backend:'podman'|'wsl'; gameImported:boolean;
  sourceGame:string; agentToken?:string; phase?:string;
  gameMode:'mount'|'copy';
}
export interface InstallOptions {game:string; storage:string; encoding:string; gameMode?:'mount'|'copy'; recordings?:string; dataRelative?:string; development?:boolean; repository?:string; content?:string[]; archives?:string[]}

export class Core {
  readonly configFile:string;
  constructor(readonly resources:string,configFile?:string,private progress?:Progress){
    const directory=process.platform==='win32'?join(process.env.APPDATA??homedir(),'AstraBridge'):
      join(process.env.XDG_CONFIG_HOME??join(homedir(),'.config'),'astrabridge');
    this.configFile=resolve(configFile??process.env.ASTRA_CONFIG??join(directory,'installation.json'));
  }
  async release():Promise<Release>{return JSON.parse(await readFile(join(this.resources,'release.json'),'utf8'));}
  async load():Promise<Installation|null>{
    try{return JSON.parse(await readFile(this.configFile,'utf8'));}
    catch(error){if((error as NodeJS.ErrnoException).code==='ENOENT')return null;throw error;}
  }
  private async save(value:Installation){
    await mkdir(dirname(this.configFile),{recursive:true,mode:0o700});
    const temporary=this.configFile+'.'+randomUUID()+'.tmp';
    await writeFile(temporary,JSON.stringify(value,null,2)+'\n',{mode:0o600});
    await rename(temporary,this.configFile);
  }
  private async exclusive<T>(operation:()=>Promise<T>):Promise<T>{
    await mkdir(dirname(this.configFile),{recursive:true,mode:0o700});
    const lock=this.configFile+'.lock';
    try{const old=JSON.parse(await readFile(lock,'utf8'));
      try{process.kill(old.pid,0);throw new Error('Another install/update is running');}
      catch(error){if((error as NodeJS.ErrnoException).code==='ESRCH')await rm(lock);else throw error;}
    }catch(error){if((error as NodeJS.ErrnoException).code!=='ENOENT')throw error;}
    const handle=await open(lock,'wx',0o600);await handle.writeFile(JSON.stringify({pid:process.pid}));
    try{return await operation();}finally{await handle.close();await rm(lock,{force:true});}
  }
  backend(config:Pick<Installation,'backend'|'storageDirectory'>):RuntimeBackend {
    return config.backend==='wsl'?new WslContainerBackend(undefined,this.progress):new PodmanBackend(config.storageDirectory,undefined,this.progress);
  }
  async prerequisites(storage:string){return this.backend({backend:process.platform==='win32'?'wsl':'podman',storageDirectory:resolve(storage)}).check();}
  async configured(){const config=await this.load();if(!config)throw new Error('AstraBridge is not installed. Open Setup or run astrabridge install.');return config;}
  async fetch(path:string,init:RequestInit={},config?:Installation):Promise<Response>{
    config??=await this.configured();
    if(!path.startsWith('/v1/')&&path!=='/health')throw new Error('Invalid runtime API path');
    const response=await fetch(`http://127.0.0.1:${config.apiPort}${path}`,{...init,
      headers:{Authorization:'Bearer '+config.token,...(config.agentToken?{'X-Astra-Session':config.agentToken}:{}),...init.headers}});
    return response;
  }
  async api(path:string,method='GET',data?:unknown,config?:Installation):Promise<any>{
    const response=await this.fetch(path,{method,headers:{'Content-Type':'application/json'},
      ...(data===undefined?{}:{body:JSON.stringify(data)})},config);
    const body=await response.json() as {ok:boolean;result:unknown;error?:string;message?:string};
    if(!response.ok||!body.ok)throw Object.assign(new Error(body.message??body.error??`HTTP ${response.status}`),{details:body});
    return body.result;
  }
  private async ready(config:Installation){
    const deadline=Date.now()+45_000;
    while(Date.now()<deadline){
      try{const health=await this.api('/health','GET',undefined,config);
        const release=await this.release();
        if(health.runtime_api!==release.runtime_api||health.game_api!==release.game_api)throw new Error('Runtime API version mismatch');
        return health;
      }catch(error){if(String(error).includes('version mismatch'))throw error;}
      await new Promise(resolve=>setTimeout(resolve,200));
    }
    throw new Error('Runtime did not become ready. Open Diagnostics or run astrabridge logs.');
  }
  async ensureDaemon(config?:Installation){
    config??=await this.configured();const backend=this.backend(config);const state=await backend.inspect(config.name);
    if(!state.exists)throw new Error('Managed container is missing. Reinstall or explicitly update runtime.');
    if(!state.running)await backend.start(config.name);
    await this.ready(config);return config;
  }
  async status(){
    const config=await this.load();const release=await this.release();
    if(!config)return {installed:false,release};
    const container=await this.backend(config).inspect(config.name);
    let runtime=null,error=null;
    if(container.running){try{runtime=await this.api('/v1/runtime/status','GET',undefined,config);}catch(e){error=String(e);}}
    return {installed:config.installed,phase:config.phase,backend:config.backend,container,runtime,error,release,
      currentDigest:config.digest,updateRequired:Boolean(release.digest&&release.digest!==config.digest),
      storageDirectory:config.storageDirectory,recordingsDirectory:config.recordingsDirectory,gameMode:config.gameMode,sourceGame:config.sourceGame};
  }
  async install(options:InstallOptions){return this.exclusive(async()=>{
    const game=resolve(options.game);if(!(await stat(game)).isDirectory())throw new Error('Select an existing Morrowind directory');
    if(!['win1250','win1251','win1252'].includes(options.encoding))throw new Error('Choose an explicit game encoding');
    const gameMode=options.gameMode??'mount';if(!['mount','copy'].includes(gameMode))throw new Error('Choose game mode mount or copy');
    if(options.repository&&!options.development)throw new Error('--repository requires --development');
    if(options.repository)await access(join(resolve(options.repository),'runtime/daemon/astra_daemon'));
    const existing=await this.load();if(existing?.installed)throw new Error('Already installed; use start or update.');
    if(existing&&existing.sourceGame!==game)throw new Error('This incomplete installation belongs to another game directory. Use a separate --config.');
    const release=await this.release();const id=randomUUID().slice(0,12);
    const config:Installation=existing??{name:'astrabridge-'+id,image:release.image,digest:release.digest,
      token:randomBytes(32).toString('hex'),gameVolume:'astrabridge-game-'+id,stateVolume:'astrabridge-state-'+id,
      apiPort:18770,rtcPort:18771,mode:options.development?'development':'production',installed:false,
      backend:process.platform==='win32'?'wsl':'podman',storageDirectory:resolve(options.storage),gameImported:false,sourceGame:game,
      recordingsDirectory:resolve(options.recordings??join(options.storage,'recordings')),gameMode,
      ...(options.repository?{repository:resolve(options.repository),buildDirectory:join(resolve(options.storage),'build')}:{}) ,
      ...(gameMode==='mount'?{gameDirectory:game}:{})};
    await mkdir(config.recordingsDirectory,{recursive:true,mode:0o700});
    if(config.buildDirectory)await mkdir(config.buildDirectory,{recursive:true});
    const backend=this.backend(config);const check=await backend.check();if(!check.available)throw new Error(check.message);
    config.phase='pulling';await this.save(config);this.progress?.('Pulling runtime image…\n');
    const digest=await backend.pull(release.image);
    if(release.digest&&digest!==release.digest)throw new Error('Pulled image does not match the Desktop release digest');
    config.digest=digest;config.image=release.image.split('@')[0]+'@'+digest;
    if(config.gameMode==='copy')await backend.createVolume(config.gameVolume);
    await backend.createVolume(config.stateVolume);
    if(config.gameMode==='copy'&&!config.gameImported){
      config.phase='importing';await this.save(config);this.progress?.(`Copying ${game} into managed game storage…\n`);
      const archive=tar.c({cwd:game,portable:true,follow:false},['.']);
      await backend.importGame(config.image,config.gameVolume,archive as unknown as Readable);
      config.gameImported=true;await this.save(config);
    }
    config.phase='configuring';await this.save(config);
    if(!(await backend.inspect(config.name)).exists)await backend.create(config);
    await backend.start(config.name);await this.ready(config);
    await this.api('/v1/runtime/import-ini','POST',{encoding:options.encoding,data_relative:options.dataRelative??'Data Files'},config);
    if(options.content||options.archives)await this.api('/v1/runtime/config','PATCH',{
      ...(options.content?{content:options.content}:{}),...(options.archives?{archives:options.archives}:{})},config);
    await backend.stop(config.name);config.installed=true;config.phase='ready';await this.save(config);
    return this.status();
  });}
  async start(gpu?:string){const config=await this.ensureDaemon();
    const release=await this.release();if(release.digest&&release.digest!==config.digest)throw new Error('Update runtime to match this Desktop before starting the game');
    if(gpu===undefined&&(process.env.__NV_PRIME_RENDER_OFFLOAD==='1'||process.env.__GLX_VENDOR_LIBRARY_NAME==='nvidia')){
      const settings=await this.api('/v1/runtime/config','GET',undefined,config);
      if(settings.graphics_gpu==='auto')gpu='nvidia';
    }
    return this.api('/v1/runtime/engine/start','POST',gpu?{gpu}:{},config);
  }
  async stop(){const config=await this.configured();const backend=this.backend(config);
    if((await backend.inspect(config.name)).running){
      try{await this.api('/v1/runtime/engine/stop','POST',{},config);}
      catch(error){this.progress?.(`Runtime API could not stop the game: ${String(error)}. Stopping container.\n`);}
      await backend.stop(config.name);
    }
    delete config.agentToken;await this.save(config);return this.status();
  }
  async restart(gpu?:string){await this.stop();return this.start(gpu);}
  async update(){return this.exclusive(async()=>{
    const config=await this.configured();const backend=this.backend(config);const release=await this.release();
    if((await backend.inspect(config.name)).running){
      const status=await this.api('/v1/runtime/status');if(status.owner.mode==='agent')throw new Error('Disconnect the agent before updating runtime');
    }
    const digest=await backend.pull(release.image);
    if(release.digest&&digest!==release.digest)throw new Error('Release digest mismatch');
    if(digest===config.digest){
      if(!(await backend.inspect(config.name)).exists)await backend.create(config);
      return this.status();
    }
    const old={...config};const wasRunning=(await backend.inspect(config.name)).running;
    if(wasRunning)await this.stop();
    const snapshot='update-'+Date.now();await backend.backup(config.image,config.stateVolume,snapshot);
    if((await backend.inspect(config.name)).exists)await backend.remove(config.name);
    config.image=release.image.split('@')[0]+'@'+digest;config.digest=digest;delete config.agentToken;
    try{
      await backend.create(config);await backend.start(config.name);await this.ready(config);
      await this.save(config);
      if(wasRunning)await this.api('/v1/runtime/engine/start','POST',{},config);else await backend.stop(config.name);
    }catch(error){
      const state=await backend.inspect(config.name);
      if(state.running)await backend.stop(config.name);if(state.exists)await backend.remove(config.name);
      await backend.restore(old.image,old.stateVolume,snapshot);await backend.create(old);await this.save(old);
      if(wasRunning){await backend.start(old.name);await this.ready(old);await this.api('/v1/runtime/engine/start','POST',{},old);}
      throw error;
    }
    return this.status();
  });}
  async connect(name='Gameplay agent'){
    await this.start();const config=await this.configured();
    const result=await this.api('/v1/agent/connect','POST',{name},config);
    config.agentToken=result.session_token;await this.save(config);
    return {...result,session_token:undefined};
  }
  async disconnect(){const config=await this.configured();const result=await this.api('/v1/agent/disconnect','POST',{},config);
    delete config.agentToken;await this.save(config);return result;}
  async game(op:string,args:Record<string,unknown>){
    const config=await this.configured();if(!config.agentToken)throw new Error('Connect first: astrabridge agent connect');
    const result=await this.api('/v1/game/command','POST',{op,args},config);
    try{return await this.materialize(result,config);}
    catch(error){return {...result,artifact_error:String(error)};}
  }
  async materialize(value:any,config:Installation):Promise<any>{
    if(Array.isArray(value))return Promise.all(value.map(v=>this.materialize(v,config)));
    if(value&&typeof value==='object')return Object.fromEntries(await Promise.all(Object.entries(value).map(async([k,v])=>[k,await this.materialize(v,config)])));
    if(typeof value!=='string'||!/^\/v1\/artifacts\/[a-f0-9]{32}$/.test(value))return value;
    const directory=join(config.storageDirectory,'exports');await mkdir(directory,{recursive:true});
    const response=await this.fetch(value,{},config);if(!response.ok||!response.body)throw new Error('Artifact is no longer available');
    if(response.headers.get('X-Astra-Artifact-Kind')==='recording'){
      const name=decodeURIComponent(response.headers.get('X-Astra-Artifact-Name')??'');
      if(name&&basename(name)===name&&!name.includes('\\')){
        const local=join(config.recordingsDirectory,name);
        try{if((await stat(local)).isFile()){await response.body.cancel();return local;}}catch{}
      }
    }
    const types:Record<string,string>={'image/png':'.png','image/svg+xml':'.svg','video/mp4':'.mp4','application/json':'.json','text/plain':'.log'};
    const extension=types[response.headers.get('content-type')?.split(';')[0]??'']??'.bin';
    const target=join(directory,basename(value)+extension);const temporary=target+'.'+randomUUID()+'.tmp';
    try{await pipeline(Readable.fromWeb(response.body as any),createWriteStream(temporary,{mode:0o600}));await rename(temporary,target);}
    catch(error){await rm(temporary,{force:true});throw error;}
    return target;
  }
  async logs(name?:string){
    const config=await this.configured();const backend=this.backend(config);
    if((await backend.inspect(config.name)).running){try{return await this.api('/v1/runtime/logs?name='+encodeURIComponent(name??'daemon.log'));}catch{}}
    return {name:'container',text:await backend.logs(config.name)};
  }
  async exportSkill(destination:string,executable:string){
    destination=resolve(destination);try{await access(destination);throw new Error('Skill destination already exists; choose a new directory');}
    catch(error){if((error as NodeJS.ErrnoException).code!=='ENOENT')throw error;}
    await cp(join(this.resources,'skill'),destination,{recursive:true,errorOnExist:true});
    await writeFile(join(destination,'installation.json'),JSON.stringify({executable,config:this.configFile},null,2)+'\n');
    return {skill:join(destination,'SKILL.md'),executable,config:this.configFile};
  }
}
