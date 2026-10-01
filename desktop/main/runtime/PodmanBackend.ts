import {mkdir,readdir,access} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {Readable} from 'node:stream';
import {checked,resourceName,run,type Runner,type Progress,type RuntimeBackend,type RuntimeSpec,type RuntimeInspection} from './RuntimeBackend';

export class PodmanBackend implements RuntimeBackend {
  readonly kind='podman' as const;
  constructor(readonly storage:string,private runner:Runner=run,private progress?:Progress){}
  private async args(){
    const graph=join(this.storage,'containers');
    const state=join(this.storage,'run','podman');
    await mkdir(graph,{recursive:true});await mkdir(state,{recursive:true});
    return ['--root',graph,'--runroot',state,'--runtime','crun'];
  }
  private async command(args:string[],input?:Readable,timeout=120_000){
    return this.runner('podman',[...await this.args(),...args],{input,timeout,progress:args.includes('pull')?this.progress:undefined});
  }
  async check(){
    try {
      if(process.platform!=='linux')throw new Error('Podman backend requires Linux');
      const version=checked(await this.runner('podman',['--version']));
      const major=version.match(/(?:version\s+)?(\d+)\.\d+/)?.[1];
      if(!major||Number(major)<5)throw new Error('Podman 5 or newer is required');
      const info=JSON.parse(checked(await this.command(['info','--format','json'])));
      checked(await this.runner('crun',['--version']));
      if(process.arch!=='x64')throw new Error('AstraBridge requires Linux x86_64');
      if(!info.host?.security?.rootless)throw new Error('This installation requires rootless Podman');
      return {available:true,version};
    }catch(error){return {available:false,version:'',message:String(error)};}
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
  async stop(name:string){checked(await this.command(['stop','--time','120',resourceName(name)],undefined,150_000));}
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
