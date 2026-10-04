import {mkdir,readdir,access,rmdir,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {constants} from 'node:fs';
import {Readable} from 'node:stream';
import {checkLinuxHost,prerequisiteReport,hostAccess,type HostAccess} from './LinuxPrerequisites';
import {checked,resourceName,run,type Runner,type Progress,type RuntimeBackend,type RuntimeSpec,type RuntimeInspection} from './RuntimeBackend';

export class PodmanBackend implements RuntimeBackend {
  readonly kind='podman' as const;
  constructor(readonly storage:string,private runner:Runner=run,private progress?:Progress,private host:HostAccess=hostAccess){}
  private async args(){
    const graph=join(this.storage,'containers');
    const state=join(this.storage,'run','podman');
    await mkdir(graph,{recursive:true});await mkdir(state,{recursive:true});
    return ['--root',graph,'--runroot',state,'--runtime','crun'];
  }
  private async command(args:string[],input?:Readable,timeout=120_000){
    return this.runner('podman',[...await this.args(),...args],{input,timeout,progress:args.includes('pull')?this.progress:undefined});
  }
  async check(gpuDevices?:string[]){
    const report=await checkLinuxHost(this.runner,this.host,gpuDevices),checks=report.checks!;
    // Startup checks need no storage selection. The actual managed store is
    // validated before install/start/update, before downloading an image.
    if(this.storage&&!checks.some(c=>c.status==='error'&&['user','podman','crun','newuidmap','newgidmap','subuid','subgid','namespaces','namespace-probe'].includes(c.id))){
      try{
        const info=JSON.parse(checked(await this.command(['info','--format','json'],undefined,20_000)));
        if(!info.host?.security?.rootless)throw new Error('Podman is not operating rootlessly.');
        for(const key of ['uidmap','gidmap'])if(!info.host.idMappings?.[key]?.some((m:any)=>m.container_id>0&&m.size>0))
          throw new Error('Podman has no usable subordinate UID/GID mappings. Check newuidmap/newgidmap permissions and your configured ranges.');
        for(const [title,path,packageName] of [
          ['Container monitor',info.host.conmon?.path,'conmon'],
          ['Container network backend',info.host.networkBackendInfo?.path,info.host.networkBackend??'netavark'],
        ])if(!path||!await this.host.accessible(path,constants.X_OK))
          checks.push({id:packageName,title,status:'error',detail:`${packageName} is missing or not executable in Podman's configuration.`,remedy:`Install/repair the ${packageName} package and Podman configuration.`});
        checks.push({id:'podman-storage',title:'Rootless Podman storage',status:'ok',detail:'Managed storage and user mappings are usable.'});
        const network=info.host.rootlessNetworkCmd;
        if(network&&['pasta','slirp4netns'].includes(network)&&!info.host[network]?.executable)
          checks.push({id:'configured-network',title:'Configured network helper',status:'error',detail:`Podman selects ${network}, but its executable is unavailable.`,remedy:`Install ${network==='pasta'?'passt':'slirp4netns'} or correct Podman rootless networking configuration.`});
      }catch(error){checks.push({id:'podman-storage',title:'Rootless Podman storage',status:'error',detail:String(error),remedy:'Check the managed storage location and rootless Podman configuration. See docs/system-requirements.md.'});}
    }
    return prerequisiteReport(checks,report.version);
  }
  async pull(image:string){
    if(image.startsWith('localhost/')){
      const local=await this.command(['image','inspect',image,'--format','{{.Digest}}']);
      if(local.code===0&&local.stdout.trim())return local.stdout.trim();
    }
    checked(await this.command(['pull',image],undefined,30*60_000));
    return checked(await this.command(['image','inspect',image,'--format','{{.Digest}}']));
  }
  async createVolume(name:string){checked(await this.command(['volume','create',resourceName(name)]));}
  async ensureImage(image:string,digest:string){
    const local=await this.command(['image','inspect',image,'--format','{{.Digest}}']);
    if(local.code===0&&local.stdout.trim()===digest)return;
    if(image.startsWith('localhost/')){await this.localImage(image);return;}
    const actual=await this.pull(image.split('@')[0]+'@'+digest);
    if(actual!==digest)throw new Error('Previous runtime digest mismatch');
  }
  private async volumeExists(name:string){
    const result=await this.command(['volume','exists',resourceName(name)]);
    if(result.code===1)return false;checked(result);return true;
  }
  async inspectStorage(spec:RuntimeSpec){
    return {state:await this.volumeExists(spec.stateVolume),game:spec.gameDirectory?null:await this.volumeExists(spec.gameVolume)};
  }
  async removeVolume(name:string){
    if(await this.volumeExists(name))checked(await this.command(['volume','rm',resourceName(name)]));
  }
  async cleanupStore(){
    // This graph/run root belongs to the selected managed store, never the
    // user's default Podman store. Preserve any other installation using it.
    for(const args of [['ps','--all','--quiet'],['volume','ls','--quiet'],['pod','ps','--quiet']])
      if(checked(await this.command(args)))return false;
    // Do not use system reset: rootless pause processes can be shared by other
    // graph roots. Delete this empty store through its UID-mapped namespace.
    checked(await this.command(['image','prune','--all','--force'],undefined,10*60_000));
    checked(await this.command(['unshare','unshare','--mount','--propagation','private','sh','-c',
      'umount -- "$1/overlay" 2>/dev/null || true; rm -rf -- "$1" "$2"',
      'astra-remove-store',join(this.storage,'containers'),join(this.storage,'run','podman')],undefined,10*60_000));
    // Podman may recreate empty bookkeeping directories as unshare exits.
    await rm(join(this.storage,'containers'),{recursive:true,force:true});
    await rm(join(this.storage,'run','podman'),{recursive:true,force:true});
    for(const path of [join(this.storage,'run'),this.storage]){
      try{await rmdir(path);}catch(error){if(!['ENOENT','ENOTEMPTY','EEXIST'].includes((error as NodeJS.ErrnoException).code??''))throw error;}
    }
    return true;
  }
  private async localImage(image:string):Promise<string>{
    if(!image.startsWith('localhost/')||!image.includes('@sha256:'))return image;
    const direct=await this.command(['image','inspect',image,'--format','{{.Id}}']);
    if(direct.code===0&&direct.stdout.trim())return direct.stdout.trim();
    // Rebuilding a local tag removes its old name but not its image. Resolve
    // that immutable manifest digest for offline snapshots and rollback.
    const digest=image.split('@')[1];
    const ids=checked(await this.command(['images','--all','--no-trunc','--format','{{.ID}}'])).split('\n');
    for(const id of new Set(ids.filter(Boolean))){
      const found=await this.command(['image','inspect',id,'--format','{{.Digest}}']);
      if(found.code===0&&found.stdout.trim()===digest)return id;
    }
    throw new Error('Pinned local runtime image is missing; build or load it before continuing');
  }
  async create(spec:RuntimeSpec){
    const args=['create','--pull=never','--http-proxy=false','--name',resourceName(spec.name),'--read-only',
      '--tmpfs','/tmp:rw,nosuid,nodev,size=512m','--cap-drop=ALL','--security-opt=no-new-privileges',
      '--stop-timeout=120','--mount',`type=volume,src=${resourceName(spec.stateVolume)},dst=/data`,
      '--mount',['type=bind',`src=${spec.recordingsDirectory}`,'dst=/data/recordings'].map(value=>
        /[,"\n]/.test(value)?'"'+value.replaceAll('"','""')+'"':value).join(','),
      '-p',`127.0.0.1:${spec.apiPort}:18770/tcp`,'-p',`127.0.0.1:${spec.rtcPort}:${spec.rtcPort}/tcp`,
      '-e',`ASTRA_API_TOKEN=${spec.token}`,'-e',`ASTRA_RTC_PORT=${spec.rtcPort}`,
      '-e',`ASTRA_MODE=${spec.mode}`,'-e',`ASTRA_IMAGE_DIGEST=${spec.digest}`];
    if(spec.gameDirectory)args.push('--mount',['type=bind',`src=${spec.gameDirectory}`,'dst=/managed-game/content','ro=true']
      .map(value=>/[,"\n]/.test(value)?'"'+value.replaceAll('"','""')+'"':value).join(','));
    else args.push('--mount',`type=volume,src=${resourceName(spec.gameVolume)},dst=/managed-game,ro=true`);
    if(spec.repository){
      if(spec.mode!=='development')throw new Error('Repository mounts require development mode');
      args.push('-v',`${spec.repository}:/src:rw`,'-v',`${join(spec.repository,'runtime')}:/opt/astrabridge/runtime:rw`);
    }
    if(spec.buildDirectory){
      if(spec.mode!=='development')throw new Error('Build mounts require development mode');
      args.push('-v',`${spec.buildDirectory}:/work/build:rw`);
    }
    let devices=spec.gpuDevices;
    if(!devices){
      devices=(await readdir('/dev/dri').catch(()=>[])).filter(name=>/^renderD\d+$/.test(name)).map(name=>'/dev/dri/'+name);
      try{await access('/dev/nvidiactl');devices.push('nvidia.com/gpu=all');}catch{}
    }
    for(const device of devices)args.push('--device',device);
    if(devices.some(device=>device.startsWith('nvidia.com/')))
      args.push('-e','NVIDIA_DRIVER_CAPABILITIES=graphics,video,utility,compute');
    // crun keeps the host user's render-device supplementary groups in rootless mode.
    args.push('--group-add','keep-groups',await this.localImage(spec.image));
    checked(await this.command(args));
  }
  async start(name:string){checked(await this.command(['start',resourceName(name)]));}
  async stop(name:string,seconds=120){checked(await this.command(['stop','--time',String(seconds),resourceName(name)],undefined,(seconds+30)*1000));}
  async remove(name:string){checked(await this.command(['rm',resourceName(name)]));}
  async inspect(name:string):Promise<RuntimeInspection>{
    const value=await this.command(['inspect',resourceName(name)]);
    if(value.code!==0){
      if(/no such|does not exist|not found/i.test(value.stderr))return {exists:false,running:false};
      checked(value);
    }
    const data=JSON.parse(value.stdout)[0];
    return {exists:true,running:data.State.Running,id:data.Id,image:data.Image,status:data.State.Status};
  }
  async logs(name:string){const result=await this.command(['logs','--tail','300',resourceName(name)]);checked(result);return result.stdout+result.stderr;}
  async importGame(image:string,volume:string,archive:Readable){
    checked(await this.command(['run','--pull=never','--http-proxy=false','--rm','-i','--network=none',
      '--mount',`type=volume,src=${resourceName(volume)},dst=/import`,
      '--entrypoint','/opt/astrabridge/python/bin/python',await this.localImage(image),'-m','astra_daemon.importer','/import'],archive,60*60_000));
  }
  private async snapshot(image:string,volume:string,id:string,operation:string){
    if(!/^[a-zA-Z0-9_-]+$/.test(id))throw new Error('Invalid snapshot ID');
    checked(await this.command(['run','--pull=never','--http-proxy=false','--rm','--network=none',
      '--mount',`type=volume,src=${resourceName(volume)},dst=/data`,
      '--entrypoint','/opt/astrabridge/python/bin/python',await this.localImage(image),'-m','astra_daemon.snapshot',operation,id],undefined,10*60_000));
  }
  async backup(image:string,volume:string,id:string){await this.snapshot(image,volume,id,'backup');}
  async restore(image:string,volume:string,id:string){await this.snapshot(image,volume,id,'restore');}
  async pruneBackups(image:string,volume:string,keep:string){await this.snapshot(image,volume,keep,'prune');}
  async removeImage(image:string){
    let resolved:string;
    try{resolved=await this.localImage(image);}catch(error){if(String(error).includes('Pinned local runtime image is missing'))return;throw error;}
    const result=await this.command(['image','rm','--no-prune',resolved]);
    if(result.code!==0&&!/no such|not known|not found/i.test(result.stderr))checked(result);
  }
}
