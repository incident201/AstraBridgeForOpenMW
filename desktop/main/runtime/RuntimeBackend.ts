import {spawn} from 'node:child_process';
import {Readable} from 'node:stream';
import {terminateProcessTree} from './process-tree';

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
export type {Progress} from './PullProgress';
import type {Progress} from './PullProgress';
export interface ProcessResult {code:number; stdout:string; stderr:string}
export type Runner=(program:string,args:string[],options?:{input?:Readable; timeout?:number; progress?:Progress; terminal?:boolean})=>Promise<ProcessResult>;

export const run:Runner=(program,args,options={})=>new Promise((resolve,reject)=>{
  const terminal = options.terminal && process.platform === 'linux';
  const quote = (value:string) => "'" + value.replaceAll("'", "'\"'\"'") + "'";
  const child = spawn(terminal ? 'script' : program, terminal
    ? ['-qefc', 'stty cols 160 rows 40 && exec ' + [program, ...args].map(quote).join(' '), '/dev/null']
    : args, {
      stdio:['pipe', 'pipe', 'pipe'], windowsHide:true, detached:process.platform !== 'win32',
      env:terminal ? {...process.env, LC_ALL:'C', TERM:'xterm', COLUMNS:'160'} : process.env,
    });
  let stdout = '', stderr = '';
  let cancellationError:Error|undefined;
  let settled = false;
  let closed!:()=>void;
  const closedPromise = new Promise<void>(resolve => closed = resolve);
  const limit = 4 * 1024 * 1024;
  const cleanup = () => {
    clearTimeout(timer);
    options.input?.off('error', inputFailed);
  };
  const finish = (error?:Error, code?:number|null) => {
    if (settled) return;
    settled = true;
    cleanup();
    if (error) reject(error);
    else resolve({code:code ?? 1, stdout, stderr});
  };
  const cancel = (error:Error) => {
    if (settled || cancellationError) return;
    cancellationError = error;
    clearTimeout(timer);
    options.input?.unpipe(child.stdin);
    child.stdin.destroy();
    void terminateProcessTree(child).catch(terminationError => {
      child.kill('SIGKILL');
      cancellationError = new Error(`${error.message}: ${String(terminationError)}`);
    }).then(async()=>{
      // Reap the child normally; a kernel/process-tree failure must not hang the caller forever.
      await new Promise<void>(resolve => {
        const reapTimer = setTimeout(resolve, 1000);
        void closedPromise.then(()=>{clearTimeout(reapTimer);resolve();});
      });
      finish(cancellationError);
    });
  };
  const timer = setTimeout(() => cancel(new Error(`${program} timed out`)), options.timeout ?? 120_000);
  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  child.stdout.on('data', (chunk:string) => {
    stdout = (stdout + chunk).slice(-limit);
    options.progress?.(chunk);
  });
  child.stderr.on('data', (chunk:string) => {
    stderr = (stderr + chunk).slice(-limit);
    options.progress?.(chunk);
  });
  const inputFailed = (error:Error) => cancel(error);
  child.once('error', error => finish(error));
  child.once('close', code => {
    closed();
    if (!cancellationError) finish(undefined, code);
  });
  child.stdin.on('error', () => {});
  if (options.input) {
    options.input.on('error', inputFailed);
    options.input.pipe(child.stdin);
  } else child.stdin.end();
});

export function checked(result:ProcessResult):string {
  if(result.code!==0)throw new Error(result.stderr.trim()||result.stdout.trim()||`Runtime command failed (${result.code})`);
  return result.stdout.trim();
}

export function resourceName(value:string):string {
  if(!/^astrabridge-[a-zA-Z0-9_-]+$/.test(value))throw new Error('Invalid managed resource name');
  return value;
}
