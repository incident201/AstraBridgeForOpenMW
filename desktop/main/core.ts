import {access,copyFile,cp,mkdir,open,readFile,rename,rm,stat,writeFile} from 'node:fs/promises';
import {basename,dirname,join,resolve} from 'node:path';
import {homedir} from 'node:os';
import {randomBytes,randomUUID} from 'node:crypto';
import {Readable} from 'node:stream';
import {pipeline} from 'node:stream/promises';
import {createWriteStream} from 'node:fs';
import * as tar from 'tar';
import {Recordings} from './recordings';
import {gameDataDirectory} from './game-data';
import {PodmanBackend} from './runtime/PodmanBackend';
import {WslContainerBackend} from './runtime/WslContainerBackend';
import type {Progress,RuntimeBackend,RuntimeSpec} from './runtime/RuntimeBackend';

export interface Release {version:string; image:string; digest:string; development?:boolean; runtime_api:number; game_api:number}
export interface RecoveryVersion {image:string;digest:string;version?:string;snapshot:string;created:number}
interface UpdateTransaction {before:Installation;snapshot:string;backedUp:boolean;replacing:boolean;wasRunning:boolean;gameWasRunning:boolean;api:{runtime_api:number;game_api:number}|null}
export interface Installation extends RuntimeSpec {
  installed:boolean; storageDirectory:string; backend:'podman'|'wsl'; gameImported:boolean;
  selectedProfile?:{id:string;name:string};
  lastStop?:{reason:'user_requested_stop';at:number};
  sourceGame:string; agentToken?:string; agentProfile?:string; phase?:string;
  gameMode:'mount'|'copy';
  version?:string;previous?:RecoveryVersion;transaction?:UpdateTransaction;retiredImages?:string[];cleanupPending?:boolean;
}
export interface InstallOptions {game:string; storage:string; encoding:string; gameMode?:'mount'|'copy'; recordings?:string; dataRelative?:string; development?:boolean; repository?:string; content?:string[]; archives?:string[]}

export class Core {
  readonly configFile:string;
  managementBusy=false;
  private lifecycleGeneration=0;
  readonly recordings=new Recordings();
  private daemonStarting:Promise<Installation>|null=null;
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
    this.managementBusy=true;
    try{return await operation();}finally{this.managementBusy=false;await handle.close();await rm(lock,{force:true});}
  }
  backend(config:Pick<Installation,'backend'|'storageDirectory'>):RuntimeBackend {
    return config.backend==='wsl'?new WslContainerBackend(undefined,this.progress):new PodmanBackend(config.storageDirectory,undefined,this.progress);
  }
  async prerequisites(storage?:string){
    const config=await this.load();
    return this.backend({backend:config?.backend??(process.platform==='win32'?'wsl':'podman'),
      storageDirectory:storage?resolve(storage):config?.storageDirectory??''}).check(config?.gpuDevices);
  }
  private async requirePrerequisites(backend:RuntimeBackend,gpuDevices?:string[]){
    const report=await backend.check(gpuDevices);
    if(!report.available)throw Object.assign(new Error('System requirements are not met.\n'+report.message),
      {details:{error:'prerequisites_missing',message:report.message,prerequisites:report}});
  }
  async configured(){const config=await this.load();if(!config)throw new Error('AstraBridge is not installed. Open Setup or run astrabridge install.');return config;}
  async fetch(path:string,init:RequestInit={},config?:Installation):Promise<Response>{
    config??=await this.configured();
    if(!path.startsWith('/v1/')&&path!=='/health')throw new Error('Invalid runtime API path');
    const response=await fetch(`http://127.0.0.1:${config.apiPort}${path}`,{...init,
      headers:{Authorization:'Bearer '+config.token,...(config.agentToken?{'X-Astra-Session':config.agentToken}:{}),...init.headers}});
    return response;
  }
  async api(path:string,method='GET',data?:unknown,config?:Installation,timeoutMs?:number):Promise<any>{
    const response=await this.fetch(path,{method,headers:{'Content-Type':'application/json'},
      ...(timeoutMs?{signal:AbortSignal.timeout(timeoutMs)}:{}),
      ...(data===undefined?{}:{body:JSON.stringify(data)})},config);
    const body=await response.json() as {ok:boolean;result:unknown;error?:string;message?:string};
    if(!response.ok||!body.ok)throw Object.assign(new Error(body.message??body.error??`HTTP ${response.status}`),{details:body});
    return body.result;
  }
  private async ready(config:Installation,expected?:{runtime_api:number;game_api:number}|null){
    const deadline=Date.now()+45_000;
    while(Date.now()<deadline){
      try{const health=await this.api('/health','GET',undefined,config);
        const release=expected===undefined?await this.release():expected;
        if(release&&(health.runtime_api!==release.runtime_api||health.game_api!==release.game_api))throw new Error('Runtime API version mismatch');
        return health;
      }catch(error){if(String(error).includes('version mismatch'))throw error;}
      await new Promise(resolve=>setTimeout(resolve,200));
    }
    throw new Error('Runtime did not become ready. Open Diagnostics or run astrabridge logs.');
  }
  async ensureDaemon(config?:Installation){
    if(this.daemonStarting)return this.daemonStarting;
    this.daemonStarting=this.startDaemon(config);
    try{return await this.daemonStarting;}finally{this.daemonStarting=null;}
  }
  private async startDaemon(config?:Installation){
    config??=await this.configured();
    if(config.phase==='removing')throw new Error('Finish removing the installation in Setup before starting');
    await this.requireStorage(config);
    if(config.transaction)throw new Error('Recover the interrupted runtime update in Setup before starting');
    const backend=this.backend(config);await this.requirePrerequisites(backend,config.gpuDevices);
    const state=await backend.inspect(config.name);
    if(!state.exists)throw new Error('Managed container is missing. Reinstall or explicitly update runtime.');
    if(!state.running){
      try{await backend.start(config.name);}
      catch(error){if(!(await backend.inspect(config.name)).running)throw error;}
    }
    await this.ready(config);return config;
  }
  async status(){
    const release=await this.release();let config:Installation|null;
    try{config=await this.load();}catch(error){return {installed:false,configured:true,configError:String(error),release};}
    if(!config)return {installed:false,release};
    let container,error:string|null=null;
    try{container=await this.backend(config).inspect(config.name);}
    catch(e){container={exists:false,running:false};error=String(e);}
    let storageState=null;
    try{storageState=await this.backend(config).inspectStorage?.(config)??null;}catch(e){error??=String(e);}
    const storageMissing=Boolean(storageState&&(!storageState.state||storageState.game===false));
    let runtime=null;
    if(container.running){try{runtime=await this.api('/v1/runtime/status','GET',undefined,config);}catch(e){error=String(e);}}
    return {session_end:config.lastStop??null,configured:true,storageState,storageMissing,removalPending:config.phase==='removing',profile:runtime?.profile??config.selectedProfile??{id:'default',name:'Default'},installed:config.installed,phase:config.phase,backend:config.backend,container,runtime,error,release,
      currentDigest:config.digest,currentVersion:config.version,previousRuntime:config.previous??null,updatePending:Boolean(config.transaction),cleanupPending:Boolean(config.cleanupPending),updateRequired:Boolean(release.digest&&release.digest!==config.digest),
      storageDirectory:config.storageDirectory,recordingsDirectory:config.recordingsDirectory,gameMode:config.gameMode,sourceGame:config.sourceGame};
  }
  async install(options:InstallOptions){return this.exclusive(async()=>{
    const game=resolve(options.game);if(!(await stat(game)).isDirectory())throw new Error('Select an existing Morrowind directory');
    const dataRelative=await gameDataDirectory(game,options.dataRelative);
    if(!['win1250','win1251','win1252'].includes(options.encoding))throw new Error('Choose an explicit game encoding');
    const gameMode=options.gameMode??'mount';if(!['mount','copy'].includes(gameMode))throw new Error('Choose game mode mount or copy');
    if(options.repository&&!options.development)throw new Error('--repository requires --development');
    if(options.repository)await access(join(resolve(options.repository),'runtime/daemon/astra_daemon'));
    const existing=await this.load();if(existing?.installed)throw new Error('Already installed; use start or update.');
    if(existing&&existing.sourceGame!==game)throw new Error('This incomplete installation belongs to another game directory. Use a separate --config.');
    const release=await this.release();const id=randomUUID().slice(0,12);
    const config:Installation=existing??{version:release.version,name:'astrabridge-'+id,image:release.image,digest:release.digest,
      token:randomBytes(32).toString('hex'),gameVolume:'astrabridge-game-'+id,stateVolume:'astrabridge-state-'+id,
      apiPort:18770,rtcPort:18771,mode:options.development?'development':'production',installed:false,
      backend:process.platform==='win32'?'wsl':'podman',storageDirectory:resolve(options.storage),gameImported:false,sourceGame:game,
      recordingsDirectory:resolve(options.recordings??join(options.storage,'recordings')),gameMode,
      ...(options.repository?{repository:resolve(options.repository),buildDirectory:join(resolve(options.storage),'build')}:{}) ,
      ...(gameMode==='mount'?{gameDirectory:game}:{})};
    const backend=this.backend(config);await this.requirePrerequisites(backend,config.gpuDevices);
    await mkdir(config.recordingsDirectory,{recursive:true,mode:0o700});
    if(config.buildDirectory)await mkdir(config.buildDirectory,{recursive:true});
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
    await this.api('/v1/runtime/import-ini','POST',{encoding:options.encoding,data_relative:dataRelative},config);
    if(options.content||options.archives)await this.api('/v1/runtime/config','PATCH',{
      ...(options.content?{content:options.content}:{}),...(options.archives?{archives:options.archives}:{})},config);
    await backend.stop(config.name);config.installed=true;config.phase='ready';await this.save(config);
    return this.status();
  });}

  private async requireStorage(config:Installation){
    const state=await this.backend(config).inspectStorage?.(config);
    if(state&&(!state.state||state.game===false))throw Object.assign(new Error('Managed storage is missing. Open Setup to reconnect your storage or reset setup for a new installation.'),{details:{error:'managed_storage_missing',storage:state}});
  }

  async resetSetup(){return this.exclusive(async()=>{
    let config:Installation|null=null;
    try{config=await this.load();}catch{} // An explicit reset also handles malformed configuration.
    if(config){
      let running=false;try{running=(await this.backend(config).inspect(config.name)).running;}catch{}
      if(running)throw new Error('Stop the runtime before resetting setup, or use Remove installation');
    }
    await rm(this.configFile,{force:true});return {reset:true};
  });}

  async uninstall(){return this.exclusive(async()=>{
    const config=await this.configured(),backend=this.backend(config);
    config.phase='removing';delete config.agentToken;await this.save(config);
    const state=await backend.inspect(config.name);
    if(state.running)await this.stop();
    if((await backend.inspect(config.name)).exists)await backend.remove(config.name);
    await backend.removeVolume(config.stateVolume);
    if(config.gameMode==='copy')await backend.removeVolume(config.gameVolume);
    const warnings:string[]=[];
    for(const image of new Set([config.image,config.previous?.image,...config.retiredImages??[]].filter((x):x is string=>Boolean(x)))){
      try{await backend.removeImage(image);}catch(error){warnings.push(String(error));}
    }
    if(backend.cleanupStore){
      if(!await backend.cleanupStore())warnings.push('Other containers or volumes use this storage; their files and shared cache were kept.');
    }
    await rm(this.configFile,{force:true});
    return {removed:true,recordingsDirectory:config.recordingsDirectory,sourceGame:config.sourceGame,warnings};
  });}
  async start(gpu?:string,profile?:string){const generation=this.lifecycleGeneration;const config=await this.ensureDaemon();
    if(generation!==this.lifecycleGeneration)throw new Error('Game startup was cancelled.');
    const release=await this.release();if(release.digest&&release.digest!==config.digest)throw new Error('Update runtime to match this Desktop before starting the game');
    if(gpu===undefined&&(process.env.__NV_PRIME_RENDER_OFFLOAD==='1'||process.env.__GLX_VENDOR_LIBRARY_NAME==='nvidia')){
      const settings=await this.api('/v1/runtime/config','GET',undefined,config);
      if(settings.graphics_gpu==='auto')gpu='nvidia';
    }
    if(generation!==this.lifecycleGeneration)throw new Error('Game startup was cancelled.');
    if(config.lastStop){delete config.lastStop;await this.save(config);}
    return this.api('/v1/runtime/engine/start','POST',{...(gpu?{gpu}:{}),...(profile?{profile}:{})},config);
  }
  async stop(){this.lifecycleGeneration++;if(this.daemonStarting)await this.daemonStarting.catch(()=>{});
    const config=await this.configured();const backend=this.backend(config);
    config.lastStop={reason:'user_requested_stop',at:Date.now()/1000};await this.save(config);
    if((await backend.inspect(config.name)).running){
      let starting=false;
      try{starting=Boolean((await this.api('/v1/runtime/status','GET',undefined,config,3000)).starting);}catch{}
      try{await this.api('/v1/runtime/engine/stop','POST',{},config,starting?8000:120000);}
      catch(error){this.progress?.(`Runtime API could not stop the game: ${String(error)}. Stopping container.\n`);}
      await backend.stop(config.name,starting?5:120);
    }
    delete config.agentToken;await this.save(config);return this.status();
  }
  async restart(gpu?:string){const config=await this.configured();await this.requirePrerequisites(this.backend(config),config.gpuDevices);await this.stop();return this.start(gpu);}
  async removeContainer(){return this.exclusive(async()=>{
    const config=await this.configured();const backend=this.backend(config);
    if(config.transaction)throw new Error('Recover the interrupted update before removing its container');
    const state=await backend.inspect(config.name);
    if(state.running)await this.stop();
    if(state.exists)await backend.remove(config.name);
    delete config.agentToken;config.phase='container-removed';await this.save(config);
    return this.status();
  });}

  private async cleanupRecovery(config:Installation){
    if(!config.previous)return;
    const backend=this.backend(config);let pending=false;const retained:string[]=[];
    try{await backend.pruneBackups(config.image,config.stateVolume,config.previous.snapshot);}
    catch(error){pending=true;this.progress?.(`Backup cleanup deferred: ${String(error)}\n`);}
    for(const image of new Set(config.retiredImages??[])){
      if(image.split('@').pop()===config.digest||image.split('@').pop()===config.previous.digest)continue;
      try{await backend.removeImage(image);}
      catch(error){retained.push(image);pending=true;this.progress?.(`Image cleanup deferred: ${String(error)}\n`);}
    }
    config.retiredImages=retained;config.cleanupPending=pending;await this.save(config);
  }
  private async recover(config:Installation){
    const transaction=config.transaction;if(!transaction)return this.status();
    const old={...transaction.before};delete old.agentToken;
    await this.requireStorage(old);
    const backend=this.backend(old);const state=await backend.inspect(old.name);
    await backend.ensureImage?.(old.image,old.digest);
    if(transaction.replacing){
      if(!transaction.backedUp)throw new Error('Recovery snapshot is not complete; data were left untouched');
      if(state.running)await backend.stop(old.name);
      if(state.exists)await backend.remove(old.name);
      await backend.restore(old.image,old.stateVolume,transaction.snapshot);
      await backend.create(old);
    }else if(!state.exists)await backend.create(old);
    if(transaction.wasRunning){
      if(!(await backend.inspect(old.name)).running)await backend.start(old.name);
      await this.ready(old,transaction.api);
      if(transaction.gameWasRunning)await this.api('/v1/runtime/engine/start','POST',{},old);
    }else if((await backend.inspect(old.name)).running)await backend.stop(old.name);
    old.phase='ready';delete old.transaction;await this.save(old);
    return this.status();
  }
  async update(){return this.exclusive(async()=>{
    const config=await this.configured();const backend=this.backend(config);const release=await this.release();
    await this.requirePrerequisites(backend,config.gpuDevices);
    if(config.phase==='removing')throw new Error('Finish removing the installation in Setup before updating');
    await this.requireStorage(config);
    // Persisted transactions always recover the old version before another attempt.
    if(config.transaction)return this.recover(config);
    const parts=(value:string|undefined)=>value?.match(/^(\d+)\.(\d+)\.(\d+)/)?.slice(1).map(Number);
    const installed=parts(config.version),requested=parts(release.version);
    if(installed&&requested&&requested.some((part,index)=>part<installed[index]&&requested.slice(0,index).every((v,i)=>v===installed[i])))
      throw new Error('This Desktop is older than the installed runtime. Use the matching newer Desktop; saved data will not be downgraded automatically');
    const digest=await backend.pull(release.image);
    if(release.digest&&digest!==release.digest)throw new Error('Release digest mismatch');
    if(digest===config.digest){
      if(!(await backend.inspect(config.name)).exists){await backend.create(config);config.phase='ready';await this.save(config);}
      if(config.cleanupPending)await this.cleanupRecovery(config);
      return this.status();
    }
    const state=await backend.inspect(config.name);
    const runtime=state.running?await this.api('/v1/runtime/status','GET',undefined,config):null;
    if(runtime?.owner.mode==='agent')throw new Error('Image downloaded. Disconnect the agent before applying the runtime update');
    const health=state.running?await this.api('/health','GET',undefined,config):null;
    const old={...config,version:config.version??health?.environment?.project_version};delete old.agentToken;
    // Ensure rollback/snapshot tooling exists before stopping or replacing anything.
    await backend.ensureImage?.(old.image,old.digest);
    const transaction:UpdateTransaction={before:old,snapshot:'update-'+Date.now()+'-'+randomUUID().slice(0,8),backedUp:false,replacing:false,
      wasRunning:state.running,gameWasRunning:Boolean(runtime?.running),api:health?{runtime_api:health.runtime_api,game_api:health.game_api}:null};
    delete config.agentToken;config.transaction=transaction;await this.save(config);
    const candidate:Installation={...old,image:release.image.split('@')[0]+'@'+digest,digest,version:release.version,phase:'ready',
      previous:{image:old.image,digest:old.digest,version:old.version,snapshot:transaction.snapshot,created:Date.now()},
      retiredImages:[...old.retiredImages??[],...(old.previous?[old.previous.image]:[])]};
    try{
      this.progress?.('Stopping runtime and completing recording…\n');
      if(state.running)await this.stop();
      this.progress?.('Backing up saves, profile, Atlas and session data…\n');
      await backend.backup(old.image,old.stateVolume,transaction.snapshot);
      transaction.backedUp=true;transaction.replacing=true;await this.save(config);
      if((await backend.inspect(old.name)).exists)await backend.remove(old.name);
      this.progress?.('Creating and checking the new runtime…\n');
      await backend.create(candidate);await backend.start(candidate.name);await this.ready(candidate);
      if(transaction.gameWasRunning)await this.api('/v1/runtime/engine/start','POST',{},candidate);
      if(!transaction.wasRunning)await backend.stop(candidate.name);
      await this.save(candidate); // Commit before any old recovery resources are removed.
    }catch(error){
      try{await this.recover(config);}
      catch(recoveryError){throw new Error(`Update failed: ${String(error)}. Recovery is pending: ${String(recoveryError)}. Use Recover interrupted update in Setup.`);}
      throw new Error(`Update failed; the previous runtime and saved data were restored. ${String(error)}`);
    }
    await this.cleanupRecovery(candidate);
    return this.status();
  });}
  private stoppedByUser(config:Installation){
    if(config.lastStop)throw Object.assign(new Error('The user stopped this session. Do not reconnect or restart without a new user request.'),
      {details:{ok:false,error:'user_requested_stop',session_end:config.lastStop,retryable:false}});
  }
  async agentStatus(){
    const config=await this.configured();
    if(config.lastStop)return {mode:'idle',connected:false,session_end:config.lastStop};
    return this.api('/v1/agent/status','GET',undefined,config);
  }
  async connect(name='Gameplay agent',profile?:string){
    this.stoppedByUser(await this.configured());
    await this.start(undefined,profile);const config=await this.configured();
    const result=await this.api('/v1/agent/connect','POST',{name,...(profile?{profile}:{})},config);
    config.agentToken=result.session_token;config.agentProfile=result.profile?.id;await this.save(config);
    return {...result,session_token:undefined};
  }
  async disconnect(){const config=await this.configured();const result=await this.api('/v1/agent/disconnect','POST',{},config);
    delete config.agentToken;await this.save(config);return result;}
  async game(op:string,args:Record<string,unknown>){
    const config=await this.configured();this.stoppedByUser(config);if(!config.agentToken)throw new Error('Connect first: astrabridge agent connect');
    let result;
    try{result=await this.api('/v1/game/command','POST',{op,args},config);}
    catch(error){if((error as any).details?.error==='user_requested_stop')throw error;this.stoppedByUser(await this.configured());throw error;}
    try{return await this.materialize(result,config);}
    catch(error){return {...result,artifact_error:String(error)};}
  }
  async materialize(value:any,config:Installation):Promise<any>{
    if(Array.isArray(value))return Promise.all(value.map(v=>this.materialize(v,config)));
    if(value&&typeof value==='object')return Object.fromEntries(await Promise.all(Object.entries(value).map(async([k,v])=>[k,await this.materialize(v,config)])));
    if(typeof value!=='string'||!/^\/v1\/artifacts\/[a-f0-9]{32}$/.test(value))return value;
    const directory=join(config.storageDirectory,'exports',config.agentProfile??'default');await mkdir(directory,{recursive:true});
    const response=await this.fetch(value,{},config);if(!response.ok||!response.body)throw new Error('Artifact is no longer available');
    if(response.headers.get('X-Astra-Artifact-Kind')==='recording'){
      const name=decodeURIComponent(response.headers.get('X-Astra-Artifact-Relative-Path')??response.headers.get('X-Astra-Artifact-Name')??'');
      if(name&&!name.includes('\\')&&name.split('/').every(part=>Boolean(part)&&part!=='.'&&part!=='..')){
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
    await this.configured();
    destination=resolve(destination);try{await access(destination);throw new Error('Skill destination already exists; choose a new directory');}
    catch(error){if((error as NodeJS.ErrnoException).code!=='ENOENT')throw error;}
    await cp(join(this.resources,'skill'),destination,{recursive:true,errorOnExist:true});
    await writeFile(join(destination,'installation.json'),JSON.stringify({executable,config:this.configFile},null,2)+'\n');
    return {skill:join(destination,'SKILL.md'),executable,config:this.configFile};
  }
  async profiles(){await this.ensureDaemon();return this.api('/v1/runtime/profiles');}
  async profile(operation:string,args:Record<string,unknown>){return this.exclusive(async()=>{
    await this.ensureDaemon();const result=await this.api('/v1/runtime/profiles/'+operation,'POST',args);
    if(['switch','delete','duplicate','rename'].includes(operation)){
      const config=await this.configured();delete config.agentToken;delete config.agentProfile;config.selectedProfile=result.active;await this.save(config);
    }
    return result;
  });}
  async deleteRecording(id:string){return this.exclusive(async()=>{
    const config=await this.configured();
    const row=(await this.recordings.list(config.recordingsDirectory)).find(row=>row.id===id);
    if(!row)throw new Error('Recording no longer exists. Refresh the list.');
    if((await this.backend(config).inspect(config.name)).running){
      // Do not delete a recording while the encoder is writing or finalizing it.
      const status=await this.api('/v1/runtime/status','GET',undefined,config,3000);
      if(status.recording&&!row.metadata)throw new Error('Stop recording before deleting an unfinished video.');
    }
    return this.recordings.remove(config.recordingsDirectory,id);
  });}
  async recordingsFolder(){
    const config=await this.configured();
    await mkdir(config.recordingsDirectory,{recursive:true});return config.recordingsDirectory;
  }
}
