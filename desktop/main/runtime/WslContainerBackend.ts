import {Readable} from 'node:stream';
import {checked,resourceName,run,type Runner,type Progress,type ProcessResult,type RuntimeBackend,type RuntimeSpec,type RuntimeInspection} from './RuntimeBackend';

function missingInspection(result:ProcessResult){
  // WSLC localizes its diagnostics. An empty JSON result means no matching object.
  return result.code===1&&result.stdout.trim()==='[]';
}
function imageInfo(result:ProcessResult){
  const rows=JSON.parse(checked(result));return Array.isArray(rows)?rows[0]:rows;
}
function imageIdentity(info:any,local=false):string {
  const digest=info?.Digest??info?.RepoDigests?.[0]?.split('@')[1]??(local?info?.Id:undefined);
  if(typeof digest!=='string'||!/^sha256:[a-f0-9]{64}$/.test(digest))throw new Error('WSL Containers did not report an immutable image identity');
  return digest;
}

/** WSL Containers only. No user distro, Docker daemon or nested Podman. */
export class WslContainerBackend implements RuntimeBackend {
  readonly kind='wsl' as const;
  constructor(private runner:Runner=run,private progress?:Progress){}
  private command(args:string[],input?:Readable,timeout=120_000){return this.runner('wslc.exe',args,{input,timeout,progress:args.includes('pull')?this.progress:undefined});}
  async check(){
    try {const version=checked(await this.command(['version']));return {available:true,version};}
    catch(error){return {available:false,version:'',message:`Install/update WSL Containers (wsl --update). ${String(error)}`};}
  }
  async pull(image:string){
    if(image.startsWith('localhost/')){
      const local=await this.command(['image','inspect',image]);
      if(local.code===0)return imageIdentity(imageInfo(local),true);
    }
    checked(await this.command(['image','pull',image],undefined,30*60_000));
    return imageIdentity(imageInfo(await this.command(['image','inspect',image])));
  }
  private async localImage(image:string){
    if(!image.startsWith('localhost/')||!image.includes('@sha256:'))return image;
    const pinned=await this.command(['image','inspect',image]);
    if(pinned.code===0)return imageInfo(pinned).Id as string;
    if(!missingInspection(pinned))checked(pinned);
    // Docker archives have an image config ID but no registry manifest digest.
    // Resolve that exact ID, never a mutable tag, for creation and rollback.
    const id=image.split('@')[1],result=await this.command(['image','inspect',id]);
    if(result.code===0&&imageInfo(result).Id===id)return id;
    if(result.code!==0&&!missingInspection(result))checked(result);
    throw new Error('Pinned local runtime image is missing; load it before continuing');
  }
  async createVolume(name:string){checked(await this.command(['volume','create',resourceName(name)]));}
  async create(spec:RuntimeSpec){
    if((spec.repository||spec.buildDirectory)&&spec.mode!=='development')throw new Error('Source/build mounts require development mode');
    checked(await this.command(['container','create','--name',resourceName(spec.name),'--gpus','all',
      '-v',`${resourceName(spec.stateVolume)}:/data`,'-v',spec.gameDirectory?`${spec.gameDirectory}:/managed-game/content:ro`:`${resourceName(spec.gameVolume)}:/managed-game:ro`,
      '-v',`${spec.recordingsDirectory}:/data/recordings`,
      '-p',`127.0.0.1:${spec.apiPort}:18770`,'-p',`127.0.0.1:${spec.rtcPort}:${spec.rtcPort}`,
      '-e',`ASTRA_API_TOKEN=${spec.token}`,'-e',`ASTRA_RTC_PORT=${spec.rtcPort}`,
      '-e',`ASTRA_MODE=${spec.mode}`,'-e',`ASTRA_IMAGE_DIGEST=${spec.digest}`,
      '-e','ASTRA_GPU_BACKEND=wsl','-e','LIBVA_DRIVER_NAME=d3d12',
      ...(spec.repository?['-v',`${spec.repository}:/src`,'-v',`${spec.repository}\\runtime:/opt/astrabridge/runtime`]:[]),
      ...(spec.buildDirectory?['-v',`${spec.buildDirectory}:/work/build`]:[]),await this.localImage(spec.image)]));
  }
  async start(name:string){checked(await this.command(['container','start',resourceName(name)]));}
  async stop(name:string){checked(await this.command(['container','stop','--time','120',resourceName(name)],undefined,150_000));}
  async remove(name:string){checked(await this.command(['container','rm',resourceName(name)]));}
  async inspect(name:string):Promise<RuntimeInspection>{
    const result=await this.command(['container','inspect',resourceName(name)]);
    if(result.code!==0){
      if(missingInspection(result))return {exists:false,running:false};checked(result);
    }
    const parsed=JSON.parse(result.stdout);const data=Array.isArray(parsed)?parsed[0]:parsed;
    return {exists:true,running:data.State?.Running===true,id:data.Id??data.ID,image:data.Image,status:data.State?.Status};
  }
  async logs(name:string){const result=await this.command(['container','logs','--tail','300',resourceName(name)]);checked(result);return result.stdout+result.stderr;}
  async importGame(image:string,volume:string,archive:Readable){
    checked(await this.command(['container','run','--rm','-i','-v',`${resourceName(volume)}:/import`,
      '--entrypoint','/opt/astrabridge/python/bin/python',await this.localImage(image),'-m','astra_daemon.importer','/import'],archive,60*60_000));
  }
  private async snapshot(image:string,volume:string,id:string,operation:string){
    if(!/^[a-zA-Z0-9_-]+$/.test(id))throw new Error('Invalid snapshot ID');
    checked(await this.command(['container','run','--rm','-v',`${resourceName(volume)}:/data`,
      '--entrypoint','/opt/astrabridge/python/bin/python',await this.localImage(image),'-m','astra_daemon.snapshot',operation,id],undefined,10*60_000));
  }
  async backup(image:string,volume:string,id:string){await this.snapshot(image,volume,id,'backup');}
  async restore(image:string,volume:string,id:string){await this.snapshot(image,volume,id,'restore');}
  async pruneBackups(image:string,volume:string,keep:string){await this.snapshot(image,volume,keep,'prune');}
  async removeImage(image:string){
    let resolved:string;
    try{resolved=await this.localImage(image);}catch(error){if(String(error).includes('Pinned local runtime image is missing'))return;throw error;}
    const existing=await this.command(['image','inspect',resolved]);
    if(missingInspection(existing))return;
    checked(existing);checked(await this.command(['image','rm',resolved]));
  }
}
