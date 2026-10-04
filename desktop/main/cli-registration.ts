import {access,realpath,link,lstat,mkdir,readFile,rename,rm,writeFile} from 'node:fs/promises';
import {constants} from 'node:fs';
import {spawn} from 'node:child_process';
import {delimiter,dirname,join,resolve} from 'node:path';
import {homedir} from 'node:os';
import {createHash,randomUUID} from 'node:crypto';
import {run,checked} from './runtime/RuntimeBackend';

interface Binding {schema:1;owner:'AstraBridge CLI';executable:string;config:string;installation:string;version:string;digest:string;binaryHash?:string;pathAdded?:boolean;disabled?:boolean}
interface WindowsPath {query(directory:string):Promise<boolean>;add(directory:string):Promise<boolean>;remove(directory:string):Promise<boolean>}
interface Options {platform?:string;binDirectory?:string;searchPath?:()=>string;applicationDirectory?:string;windowsPath?:WindowsPath;removeLauncher?:(path:string)=>Promise<void>;deferRemoval?:(path:string,hash:string)=>Promise<void>}
const marker='# AstraBridge CLI registration v1\n# ';
const hash=(bytes:Buffer|string)=>createHash('sha256').update(bytes).digest('hex');
const quote=(value:string)=>"'"+value.replaceAll("'","'\"'\"'")+"'";
const same=(a:string,b:string,windows:boolean)=>windows?resolve(a).toLowerCase()===resolve(b).toLowerCase():resolve(a)===resolve(b);
async function sameFile(a:string,b:string,windows:boolean){return same(await realpath(a).catch(()=>a),await realpath(b).catch(()=>b),windows);}
function payload(binding:Binding){return Buffer.from(JSON.stringify(binding)).toString('base64');}
function linuxLauncher(binding:Binding){return '#!/bin/sh\n'+marker+payload(binding)+`\nexport ASTRA_CONFIG=${quote(binding.config)}
if [ ! -f ${quote(binding.executable)} ] || [ ! -x ${quote(binding.executable)} ]; then
  printf '%s\\n' 'AstraBridge application is missing. Open the current application and enable the CLI command in Setup.' >&2
  exit 127
fi
exec ${quote(binding.executable)} "$@"
`;}
function windowsTarget(binding:Binding){
 return '\ufeff; AstraBridge CLI registration v1\r\n; '+payload(binding)+'\r\n[AstraBridgeCLI]\r\nSchema='+(binding.disabled?'0':'1')+'\r\nLauncherHash='+(binding.binaryHash??'')+'\r\nExecutable="'+binding.executable+'"\r\nConfig="'+binding.config+'"\r\n';
}
async function exists(path:string){try{return await lstat(path);}catch(e){if((e as NodeJS.ErrnoException).code==='ENOENT')return null;throw e;}}
async function atomicFile(path:string,data:Buffer|string,mode=0o600,replace=true){
 const tmp=path+'.'+randomUUID()+'.tmp';
 try{await writeFile(tmp,data,{mode,flag:'wx'});if(replace)await rename(tmp,path);else await link(tmp,path);}finally{await rm(tmp,{force:true});}
}

/** A user-owned forwarding command. It contains no token or profile selection. */
export class CliRegistration {
 readonly windows:boolean;readonly directory:string;readonly executable:string;private target:string;
 private searchPath:()=>string;private windowsPath:WindowsPath;private removeLauncher:(path:string)=>Promise<void>;private deferRemoval:(path:string,hash:string)=>Promise<void>;
 private applicationDirectory:string|undefined;
 constructor(private resources:string,options:Options={}){
  this.windows=(options.platform??process.platform)==='win32';
  this.directory=options.binDirectory??(this.windows?join(process.env.LOCALAPPDATA??homedir(),'AstraBridge','cli','bin'):join(homedir(),'.local','bin'));
  this.executable=join(this.directory,this.windows?'astrabridge.exe':'astrabridge');
  this.target=this.windows?join(this.directory,'cli-target.ini'):this.executable;
  this.searchPath=options.searchPath??(()=>process.env.PATH??'');
  this.applicationDirectory=options.applicationDirectory??(!this.windows?process.env.APPDIR:undefined);
  this.removeLauncher=options.removeLauncher??(path=>rm(path));
  this.deferRemoval=options.deferRemoval??((path,hash)=>new Promise<void>((resolve,reject)=>{
   const child=spawn(join(resources,'cli-launcher.exe'),['--remove-launcher',path,hash],{detached:true,stdio:'ignore',windowsHide:true});
   child.once('error',reject);child.once('spawn',()=>{child.unref();resolve();});
  }));
  const pathOperation=async(action:string,directory:string)=>{
   const result=await run(join(resources,'cli-launcher.exe'),['--user-path',action,directory]);
   return JSON.parse(checked(result)) as {present:boolean;changed:boolean};
  };
  this.windowsPath=options.windowsPath??{query:async d=>(await pathOperation('query',d)).present,
   add:async d=>(await pathOperation('add',d)).changed,remove:async d=>(await pathOperation('remove',d)).changed};
 }
 private async binding():Promise<Binding|null>{
  const info=await exists(this.target);if(!info)return null;
  if(!info.isFile())throw Error('CLI launcher or registration is not an AstraBridge-owned regular file.');
  const bytes=await readFile(this.target),text=bytes.toString(this.windows?'utf16le':'utf8');
  const prefix=this.windows?'\ufeff; AstraBridge CLI registration v1\r\n; ':'#!/bin/sh\n'+marker;
  if(!text.startsWith(prefix))throw Error('Another file already occupies the CLI command location.');
  let b:Binding;
  try{b=JSON.parse(Buffer.from(text.slice(prefix.length).split(/\r?\n/)[0],'base64').toString('utf8'));}
  catch{throw Error('CLI registration is damaged. The existing file was not changed.');}
  if(b.schema!==1||b.owner!=='AstraBridge CLI'||!['executable','config','installation','version','digest'].every(k=>typeof (b as any)[k]==='string'))throw Error('Unrecognized CLI registration.');
  if(text!==(this.windows?windowsTarget(b):linuxLauncher(b)))throw Error('CLI launcher was modified outside AstraBridge. The existing file was not changed.');
  return b;
 }
 private async ownedBinary(binding:Binding|null){
  const info=await exists(this.executable);if(!info)return false;
  if(!info.isFile())throw Error('Another file or link occupies the CLI command location.');
  if(this.windows&&(!binding?.binaryHash||hash(await readFile(this.executable))!==binding.binaryHash))throw Error('The existing CLI executable does not belong to this registration.');
  return true;
 }
 private async firstCommand(){
  for(const directory of this.searchPath().split(this.windows?';':delimiter).filter(Boolean)){
   // AppRun prepends its private mount to PATH. Its bundled entry point is not
   // a host command and disappears when the AppImage exits. Keep scanning the
   // remaining PATH so actual host conflicts are still detected.
   if(this.applicationDirectory&&await sameFile(directory,this.applicationDirectory,this.windows))continue;
   for(const name of this.windows?['astrabridge.com','astrabridge.exe','astrabridge.bat','astrabridge.cmd']:['astrabridge']){
    const path=join(directory.replace(/^"|"$/g,''),name);
    try{await access(path,this.windows?constants.F_OK:constants.X_OK);if((await lstat(path)).isDirectory())continue;return path;}catch{}
   }
  }
  return null;
 }
 async status(config?:string,installation?:string){
  let b:Binding|null=null,error:string|undefined,owned=false;
  try{b=await this.binding();owned=await this.ownedBinary(b);}catch(e){error=(e as Error).message;}
  const first=await this.firstCommand(),pathReady=Boolean(first&&await sameFile(first,this.executable,this.windows)&&owned&&!error&&!b?.disabled);
  const matches=Boolean(b&&(!config||await sameFile(b.config,config,this.windows))&&(!installation||b.installation===installation));
  let targetAvailable=false;if(b)try{await access(b.executable,this.windows?constants.F_OK:constants.X_OK);targetAvailable=true;}catch{}
  return {enabled:Boolean(b&&owned&&!error&&!b.disabled),removalPending:Boolean(b?.disabled),command:'astrabridge',executable:this.executable,
   config:b?.config,application:b?.executable,version:b?.version,digest:b?.digest,installation:b?.installation,
   matches,pathReady,targetAvailable,error,shadowedBy:first&&!pathReady?first:null,
   guidance:pathReady?'Use astrabridge from any directory.':this.windows?'Open a new terminal or restart the agent client to refresh PATH.':
    `Add ${this.directory} to PATH once, then restart the terminal or agent client. Bash/zsh: export PATH=${quote(this.directory)}:"$PATH". Fish: fish_add_path ${quote(this.directory)}.`};
 }
 private async write(binding:Binding,replace=true){
  await atomicFile(this.target,this.windows?Buffer.from(windowsTarget(binding),'utf16le'):linuxLauncher(binding),this.windows?0o600:0o755,replace);
 }
 async install(application:string,config:string,installation:string,version:string,digest:string){
  application=resolve(application);config=resolve(config);
  if(await sameFile(application,this.executable,this.windows))throw Error('Keep the AppImage/EXE outside the CLI launcher location before enabling the command.');
  await access(application,this.windows?constants.F_OK:constants.X_OK);
  const previous=await this.binding();const present=await this.ownedBinary(previous);
  const first=await this.firstCommand();
  if(first&&!(await sameFile(first,this.executable,this.windows))&&!(await sameFile(first,application,this.windows)))throw Error(`Another astrabridge command is already in PATH: ${first}. Resolve this conflict before enabling the CLI command.`);
  await mkdir(this.directory,{recursive:true,mode:0o700});
  let added=false,created=false;
  try{
   let binaryHash=previous?.binaryHash;
   if(this.windows&&!present){
    const binary=await readFile(join(this.resources,'cli-launcher.exe'));binaryHash=hash(binary);
    await writeFile(this.executable,binary,{flag:'wx',mode:0o755});created=true;
   }
   if(this.windows)added=await this.windowsPath.add(this.directory);
   const binding:Binding={schema:1,owner:'AstraBridge CLI',executable:application,config,installation,version,digest,
    ...(this.windows?{binaryHash,pathAdded:added||previous?.pathAdded||false}:{})};
   await this.write(binding,Boolean(previous));
  }catch(e){if(created)await rm(this.executable,{force:true});if(added)await this.windowsPath.remove(this.directory);throw e;}
  return this.status(config,installation);
 }
 async refresh(application:string,config:string,installation:string,version:string,digest:string){
  const b=await this.binding();
  if(!b||b.disabled||!(await sameFile(b.config,config,this.windows))||b.installation!==installation)return false;
  if(!await this.ownedBinary(b))throw Error('The CLI command is missing. Enable it again in Setup.');
  await access(application,this.windows?constants.F_OK:constants.X_OK);
  if(await sameFile(application,this.executable,this.windows))throw Error('Cannot point the CLI launcher to itself.');
  await this.write({...b,executable:resolve(application),version,digest});return true;
 }
 async uninstall(config:string){
  const b=await this.binding();if(!b||!(await sameFile(b.config,config,this.windows)))return {removed:false};
  // Verify both files before changing either; never remove a replacement executable.
  const present=await this.ownedBinary(b);
  if(this.windows&&b.pathAdded)await this.windowsPath.remove(this.directory);
  if(this.windows){
   await this.write({...b,disabled:true,pathAdded:false});
   if(present)try{await this.removeLauncher(this.executable);}catch(error){
    if(!['EPERM','EACCES','EBUSY'].includes((error as NodeJS.ErrnoException).code??''))throw error;
    await this.deferRemoval(this.executable,b.binaryHash!);return {removed:true,cleanupPending:true};
   }
  }
  await rm(this.target,{force:true});return {removed:true};
 }
}

export function applicationExecutable(){
 if(process.env.APPIMAGE)return resolve(process.env.APPIMAGE);
 if(process.env.ASTRA_EXECUTABLE)return resolve(process.env.ASTRA_EXECUTABLE);
 if(process.versions.electron)return join(dirname(process.execPath),process.platform==='win32'?'astrabridge.exe':'astrabridge');
 return undefined;
}
