import {spawn, type ChildProcessWithoutNullStreams} from 'node:child_process';
import {Readable} from 'node:stream';

export interface RuntimeSpec {
  name:string; image:string; digest:string; token:string; gameVolume:string; stateVolume:string;
  apiPort:number; rtcPort:number; mode:'production'|'development';
  recordingsDirectory:string;
  gameDirectory?:string;
  repository?:string;
  buildDirectory?:string;
  gpuDevices?:string[];
}
export interface RuntimeInspection {exists:boolean; running:boolean; id?:string; image?:string; status?:string}
export interface StorageInspection {state:boolean;game:boolean|null}
export interface PrerequisiteCheck {id:string; title:string; status:'ok'|'warning'|'error'; detail:string; remedy?:string}
export interface PrerequisiteReport {available:boolean; version:string; message?:string; checks?:PrerequisiteCheck[]}
export interface RuntimeBackend {
  readonly kind:'podman'|'wsl';
  check(gpuDevices?:string[]):Promise<PrerequisiteReport>;
  pull(image:string):Promise<string>;
  ensureImage?(image:string,digest:string):Promise<void>;
  inspectStorage?(spec:RuntimeSpec):Promise<StorageInspection>;
  removeVolume(name:string):Promise<void>;
  cleanupStore?():Promise<boolean>;
  createVolume(name:string):Promise<void>;
  create(spec:RuntimeSpec):Promise<void>;
  start(name:string):Promise<void>;
  stop(name:string,seconds?:number):Promise<void>;
  remove(name:string):Promise<void>;
  inspect(name:string):Promise<RuntimeInspection>;
  logs(name:string):Promise<string>;
  importGame(image:string,volume:string,archive:Readable):Promise<void>;
  backup(image:string,volume:string,id:string):Promise<void>;
  restore(image:string,volume:string,id:string):Promise<void>;
  pruneBackups(image:string,volume:string,keep:string):Promise<void>;
  removeImage(image:string):Promise<void>;
}
export type Progress=(message:string)=>void;
export interface ProcessResult {code:number; stdout:string; stderr:string}
export type Runner=(program:string,args:string[],options?:{input?:Readable; timeout?:number; progress?:Progress})=>Promise<ProcessResult>;

export const run:Runner=(program,args,options={})=>new Promise((resolve,reject)=>{
  const child=spawn(program,args,{stdio:['pipe','pipe','pipe'],windowsHide:true});
  let stdout='',stderr='';
  const limit=4*1024*1024;
  const timer=setTimeout(()=>{child.kill();reject(new Error(`${program} timed out`));},options.timeout??120_000);
  child.on('error',error=>{clearTimeout(timer);reject(error);});
  child.stdout.on('data',(chunk:Buffer)=>{stdout=(stdout+chunk.toString()).slice(-limit);options.progress?.(chunk.toString());});
  child.stderr.on('data',(chunk:Buffer)=>{stderr=(stderr+chunk.toString()).slice(-limit);options.progress?.(chunk.toString());});
  child.on('close',code=>{clearTimeout(timer);resolve({code:code??1,stdout,stderr});});
  child.stdin.on('error',()=>{});
  if(options.input){options.input.on('error',error=>{child.kill();clearTimeout(timer);reject(error);});options.input.pipe(child.stdin);}
  else child.stdin.end();
});

export function checked(result:ProcessResult):string {
  if(result.code!==0)throw new Error(result.stderr.trim()||result.stdout.trim()||`Runtime command failed (${result.code})`);
  return result.stdout.trim();
}

export function resourceName(value:string):string {
  if(!/^astrabridge-[a-zA-Z0-9_-]+$/.test(value))throw new Error('Invalid managed resource name');
  return value;
}
