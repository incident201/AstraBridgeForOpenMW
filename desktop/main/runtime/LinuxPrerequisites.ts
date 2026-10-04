import {access,readFile,readdir} from 'node:fs/promises';
import {constants} from 'node:fs';
import {delimiter,join} from 'node:path';
import {userInfo} from 'node:os';
import {run,type Runner,type PrerequisiteCheck,type PrerequisiteReport} from './RuntimeBackend';

export interface HostAccess {
  platform:string; arch:string; uid:number; username:string;
  read(path:string):Promise<string>;
  list(path:string):Promise<string[]>;
  accessible(path:string,mode:number):Promise<boolean>;
  executable(name:string):Promise<boolean>;
}
export const hostAccess:HostAccess={
  platform:process.platform,arch:process.arch,uid:process.getuid?.()??-1,username:userInfo().username,
  read:async path=>readFile(path,'utf8'),list:async path=>readdir(path),
  accessible:async(path,mode)=>{try{await access(path,mode);return true;}catch{return false;}},
  executable:async name=>{
    for(const directory of (process.env.PATH??'').split(delimiter).filter(Boolean)){
      try{await access(join(directory,name),constants.X_OK);return true;}catch{}
    }
    return false;
  },
};

export function prerequisiteReport(checks:PrerequisiteCheck[],version=''):PrerequisiteReport {
  const errors=checks.filter(check=>check.status==='error');
  return {available:errors.length===0,version,checks,
    ...(errors.length?{message:errors.map(check=>`${check.title}: ${check.detail}${check.remedy?' '+check.remedy:''}`).join('\n')}:{} )};
}

/** Read host capabilities without installing packages, pulling images or starting containers. */
export async function checkLinuxHost(runner:Runner=run,host:HostAccess=hostAccess,gpuDevices?:string[]):Promise<PrerequisiteReport>{
  const checks:PrerequisiteCheck[]=[];
  const add=(id:string,title:string,status:PrerequisiteCheck['status'],detail:string,remedy?:string)=>checks.push({id,title,status,detail,...(remedy?{remedy}:{})});
  const execute=async(program:string,args:string[])=>{
    try{const r=await runner(program,args,{timeout:15_000});return {ok:r.code===0,text:r.stdout.trim(),error:r.stderr.trim()};}
    catch(error){return {ok:false,text:'',error:String(error)};}
  };
  if(host.platform!=='linux'||host.arch!=='x64'){
    add('platform','Linux x86_64','error',`Detected ${host.platform}/${host.arch}.`,'Use the matching AstraBridge package on a supported system.');
    return prerequisiteReport(checks);
  }
  add('user','Rootless user',host.uid===0?'error':'ok',host.uid===0?'AstraBridge is running as root.':`Running as ${host.username}.`,
    host.uid===0?'Launch AstraBridge as your regular desktop user, without sudo.':undefined);
  const tools=await Promise.all(['podman','crun','newuidmap','newgidmap','pasta','slirp4netns','unshare','umount','rm','script','stty'].map(async name=>[name,await host.executable(name)] as const));
  const has=Object.fromEntries(tools);
  let version='';
  if(has.podman){
    const result=await execute('podman',['--version']);version=result.text;
    const major=version.match(/(?:version\s+)?(\d+)\.\d+/)?.[1];
    const valid=result.ok&&Number(major)>=5;
    add('podman','Podman 5+',valid?'ok':'error',result.text||result.error,valid?undefined:'Install or update the podman package to version 5 or newer.');
  }else add('podman','Podman 5+','error','podman was not found in PATH.','Install podman.');
  if(has.crun){
    const result=await execute('crun',['--version']);
    add('crun','crun',result.ok?'ok':'error',result.ok?result.text.split('\n')[0]:result.error,result.ok?undefined:'Install or repair crun.');
  }else add('crun','crun','error','crun was not found in PATH.','Install crun; AstraBridge selects it explicitly.');
  for(const name of ['newuidmap','newgidmap'])add(name,name,has[name]?'ok':'error',has[name]?'Available.':'Not found in PATH.',
    has[name]?undefined:'Install uidmap (Debian/Ubuntu) or shadow (Arch/CachyOS).');
  for(const name of ['unshare','umount','rm'])add('cleanup-'+name,name,has[name]?'ok':'error',has[name]?'Available for rootless storage cleanup.':'Not found in PATH.',has[name]?undefined:`Install ${name==='rm'?'coreutils':'util-linux'}.`);
  add('pull-progress','Download progress terminal',has.script&&has.stty?'ok':'error',has.script&&has.stty?'script and stty are available.':'script or stty was not found in PATH.',has.script&&has.stty?undefined:'Install util-linux and coreutils (script and stty are used to read Podman download counters).');
  for(const [id,path] of [['subuid','/etc/subuid'],['subgid','/etc/subgid']]){
    const text=await host.read(path).catch(()=>'');
    let found=text.split('\n').some(line=>{
      const [name,start,count]=line.trim().split(':');
      return (name===host.username||name===String(host.uid))&&/^\d+$/.test(start??'')&&Number(count)>0;
    });
    if(!found&&await host.executable('getsubids')){
      const lookup=await execute('getsubids',id==='subgid'?['-g',host.username]:[host.username]);
      found=lookup.ok&&lookup.text.split('\n').some(line=>/:\s+\S+\s+\d+\s+[1-9]\d*\s*$/.test(line));
    }
    add(id,`Subordinate ${id==='subuid'?'UID':'GID'} range`,found?'ok':'error',found?`${host.username} has an allocated range.`:`No range for ${host.username} in ${path} or the configured subid provider.`,
      found?undefined:`Ask your administrator to allocate a non-overlapping range in ${path}.`);
  }
  const limits=await Promise.all(['/proc/sys/user/max_user_namespaces','/proc/sys/kernel/unprivileged_userns_clone'].map(path=>host.read(path).catch(()=>'')));
  const disabled=limits.some(value=>value.trim()==='0');
  add('namespaces','User namespaces',disabled?'error':'ok',disabled?'Unprivileged user namespaces are disabled.':'Kernel namespace limits allow rootless containers.',
    disabled?'Enable unprivileged user namespaces according to your distribution policy.':undefined);
  if(!disabled&&await host.executable('unshare')){
    const result=await execute('unshare',['--user','--map-root-user','true']);
    add('namespace-probe','User namespace creation',result.ok?'ok':'warning',result.ok?'An unprivileged user namespace can be created.':result.error,
      result.ok?undefined:'The generic namespace probe was denied. The managed-storage check will verify Podman itself, which may have a different security profile.');
  }
  add('network','Rootless networking',has.pasta||has.slirp4netns?'ok':'error',has.pasta?'pasta is available (passt package).':has.slirp4netns?'slirp4netns is available; Podman must be configured to use it.':'Neither pasta nor slirp4netns was found.',
    has.pasta||has.slirp4netns?undefined:'Install passt, which provides pasta, the default for Podman 5+.');
  const devices=gpuDevices?.filter(path=>path.startsWith('/dev/dri/renderD'))??
    (await host.list('/dev/dri').catch(()=>[])).filter(name=>/^renderD\d+$/.test(name)).map(name=>'/dev/dri/'+name);
  const readable=await Promise.all(devices.map(device=>host.accessible(device,constants.R_OK|constants.W_OK)));
  const denied=devices.filter((_,index)=>!readable[index]);
  add('render','GPU render devices',denied.length?'error':devices.length?'ok':'warning',
    denied.length?`No read/write access to ${denied.join(', ')}.`:devices.length?devices.join(', '):'No DRM render device is available.',
    denied.length?'Grant this user GPU access through your distribution\'s render/video group or device ACL, then log in again.':!devices.length?'Install/configure your GPU driver for hardware rendering. Software mode remains available.':undefined);
  const vendors=await Promise.all(devices.map(device=>host.read(`/sys/class/drm/${device.split('/').at(-1)}/device/vendor`).then(v=>v.trim()).catch(()=>'')));
  for(let index=0;index<devices.length;index++){
    const vendor=vendors[index],name=vendor==='0x8086'?'Intel':vendor==='0x1002'?'AMD':vendor==='0x10de'?'NVIDIA':'GPU';
    const uevent=await host.read(`/sys/class/drm/${devices[index].split('/').at(-1)}/device/uevent`).catch(()=>''),driver=uevent.match(/^DRIVER=(.+)$/m)?.[1];
    add('driver-'+index,`${name} kernel driver`,driver?'ok':'warning',driver?`${devices[index]}: ${driver}.`:`Cannot identify the kernel driver for ${devices[index]}.`,
      driver?undefined:'Check the host GPU driver and firmware. The runtime will also verify hardware OpenGL before launching the game.');
  }
  // Match the backend's default device injection, including hybrid systems.
  const nvidia=gpuDevices?gpuDevices.some(device=>device.startsWith('nvidia.com/')):
    vendors.includes('0x10de')||await host.accessible('/dev/nvidiactl',constants.F_OK);
  if(nvidia){
    const driver=await execute('nvidia-smi',['--query-gpu=name,driver_version','--format=csv,noheader']);
    add('nvidia-driver','NVIDIA driver',driver.ok?'ok':'error',driver.ok?driver.text:driver.error||'nvidia-smi failed.',
      driver.ok?undefined:'Install or repair the host NVIDIA driver; nvidia-smi must work as this user.');
    if(driver.ok&&driver.text.split('\n').some(line=>Number(line.split(',').at(-1)?.trim().split('.')[0])<570))
      add('nvenc','NVIDIA recording','warning','The bundled NVENC encoder needs driver 570 or newer.','Update the driver for NVENC, or use CPU recording.');
    if(!await host.executable('nvidia-ctk'))add('nvidia-toolkit','NVIDIA Container Toolkit / CDI','error','nvidia-ctk was not found. A working host driver alone does not expose NVIDIA to containers.',
      'Install nvidia-container-toolkit, then run nvidia-ctk cdi list. It must include nvidia.com/gpu=all.');
    else{
      const cdi=await execute('nvidia-ctk',['cdi','list']),valid=cdi.ok&&cdi.text.split(/\s+/).includes('nvidia.com/gpu=all');
      add('nvidia-cdi','NVIDIA CDI devices',valid?'ok':'error',valid?'nvidia.com/gpu=all is registered.':cdi.error||'No usable nvidia.com/gpu=all CDI entry.',
        valid?undefined:'Refresh CDI after installing/updating the driver: sudo mkdir -p /etc/cdi && sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml. Then run nvidia-ctk cdi list.');
    }
  }
  return prerequisiteReport(checks,version);
}
