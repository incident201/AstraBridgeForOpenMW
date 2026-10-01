import {Readable} from 'node:stream';
import {checked,resourceName,run,type Runner,type Progress,type RuntimeBackend,type RuntimeSpec,type RuntimeInspection} from './RuntimeBackend';

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
    checked(await this.command(['image','pull',image],undefined,30*60_000));
    const rows=JSON.parse(checked(await this.command(['image','inspect',image])));
    const imageInfo=Array.isArray(rows)?rows[0]:rows;
    const digest=imageInfo.Digest??imageInfo.RepoDigests?.[0]?.split('@')[1];
    if(typeof digest!=='string'||!digest.startsWith('sha256:'))throw new Error('WSL Containers did not report an OCI digest');
    return digest;
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
      ...(spec.buildDirectory?['-v',`${spec.buildDirectory}:/work/build`]:[]),spec.image]));
  }
  async start(name:string){checked(await this.command(['container','start',resourceName(name)]));}
  async stop(name:string){checked(await this.command(['container','stop','--time','120',resourceName(name)],undefined,150_000));}
  async remove(name:string){checked(await this.command(['container','rm',resourceName(name)]));}
  async inspect(name:string):Promise<RuntimeInspection>{
    const result=await this.command(['container','inspect',resourceName(name)]);
    if(result.code!==0){
      if(/no such|does not exist|not found/i.test(result.stderr))return {exists:false,running:false};checked(result);
    }
    const parsed=JSON.parse(result.stdout);const data=Array.isArray(parsed)?parsed[0]:parsed;
    return {exists:true,running:data.State?.Running===true,id:data.Id??data.ID,image:data.Image,status:data.State?.Status};
  }
  async logs(name:string){const result=await this.command(['container','logs','--tail','300',resourceName(name)]);checked(result);return result.stdout+result.stderr;}
  async importGame(image:string,volume:string,archive:Readable){
    checked(await this.command(['container','run','--rm','-i','-v',`${resourceName(volume)}:/import`,
      '--entrypoint','/opt/astrabridge/python/bin/python',image,'-m','astra_daemon.importer','/import'],archive,60*60_000));
  }
  private async snapshot(image:string,volume:string,id:string,operation:string){
    if(!/^[a-zA-Z0-9_-]+$/.test(id))throw new Error('Invalid snapshot ID');
    checked(await this.command(['container','run','--rm','-v',`${resourceName(volume)}:/data`,
      '--entrypoint','/opt/astrabridge/python/bin/python',image,'-m','astra_daemon.snapshot',operation,id],undefined,10*60_000));
  }
  async backup(image:string,volume:string,id:string){await this.snapshot(image,volume,id,'backup');}
  async restore(image:string,volume:string,id:string){await this.snapshot(image,volume,id,'restore');}
  async pruneBackups(image:string,volume:string,keep:string){await this.snapshot(image,volume,keep,'prune');}
  async removeImage(image:string){
    const result=await this.command(['image','rm',image]);
    if(result.code!==0&&!/no such|not found/i.test(result.stderr))checked(result);
  }
}
