import test from 'node:test';
import assert from 'node:assert/strict';
import {checkLinuxHost,type HostAccess} from '../main/runtime/LinuxPrerequisites';
import {PodmanBackend} from '../main/runtime/PodmanBackend';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import type {Runner} from '../main/runtime/RuntimeBackend';

function fixture(){
  const files=new Map<string,string>([['/etc/subuid','tester:100000:65536'],['/etc/subgid','tester:100000:65536'],
    ['/proc/sys/user/max_user_namespaces','10000'],['/proc/sys/kernel/unprivileged_userns_clone','1'],
    ['/sys/class/drm/renderD128/device/vendor','0x8086'],['/sys/class/drm/renderD128/device/uevent','DRIVER=i915']]);
  const executables=new Set(['podman','crun','newuidmap','newgidmap','pasta','unshare','umount','rm']);
  const devices=new Set(['/dev/dri/renderD128']);const calls:string[][]=[];
  const responses=new Map([['podman','podman version 6.1.2'],['crun','crun version 1.30'],['nvidia-smi','NVIDIA RTX, 615.71.09'],['nvidia-ctk','nvidia.com/gpu=0\nnvidia.com/gpu=all']]);
  const host:HostAccess={platform:'linux',arch:'x64',uid:1000,username:'tester',
    read:async path=>{if(!files.has(path))throw new Error('ENOENT');return files.get(path)!;},
    list:async path=>path==='/dev/dri'?['renderD128']:[],accessible:async path=>devices.has(path),
    executable:async name=>executables.has(name)};
  const runner:Runner=async(program,args)=>{calls.push([program,...args]);return {code:0,stdout:responses.get(program)??'',stderr:''};};
  return {host,runner,files,executables,devices,responses,calls};
}
test('Intel and AMD need kernel/render access, not NVIDIA packages',async()=>{
  for(const [vendor,driver] of [['0x8086','xe'],['0x1002','amdgpu']]){
    const f=fixture();f.files.set('/sys/class/drm/renderD128/device/vendor',vendor);f.files.set('/sys/class/drm/renderD128/device/uevent','DRIVER='+driver);
    const report=await checkLinuxHost(f.runner,f.host);
    assert.equal(report.available,true);assert.ok(report.checks?.some(c=>c.detail.endsWith(driver+'.')));
    assert.ok(!f.calls.some(c=>c[0].startsWith('nvidia')));
  }
});
test('missing host tools are reported together, including NVIDIA on a hybrid host',async()=>{
  const f=fixture();f.executables.clear();f.devices.add('/dev/nvidiactl');
  const r=await checkLinuxHost(f.runner,f.host);assert.equal(r.available,false);
  for(const id of ['podman','crun','newuidmap','newgidmap','network','nvidia-toolkit'])
    assert.equal(r.checks?.find(c=>c.id===id)?.status,'error',id);
  assert.match(r.message!,/nvidia-container-toolkit/);
  assert.ok(!f.calls.some(c=>['pull','run','start','install'].some(v=>c.includes(v))));
});
test('NVIDIA needs a usable driver and registered CDI, not just an installed toolkit',async()=>{
  const f=fixture();f.devices.add('/dev/nvidiactl');f.executables.add('nvidia-ctk');
  f.responses.set('nvidia-ctk','nvidia.com/gpu=0');
  assert.equal((await checkLinuxHost(f.runner,f.host)).checks?.find(c=>c.id==='nvidia-cdi')?.status,'error');
  f.responses.set('nvidia-ctk','nvidia.com/gpu=all');
  assert.equal((await checkLinuxHost(f.runner,f.host)).available,true);
  const broken:Runner=async(p,a,o)=>p==='nvidia-smi'?{code:1,stdout:'',stderr:'driver/library mismatch'}:f.runner(p,a,o);
  assert.match((await checkLinuxHost(broken,f.host)).message!,/driver\/library mismatch/);
});
test('explicit Mesa device set does not require an unused NVIDIA integration',async()=>{
  const f=fixture();f.devices.add('/dev/nvidiactl');
  assert.equal((await checkLinuxHost(f.runner,f.host,['/dev/dri/renderD128'])).available,true);
});
test('bad mapping, permissions and disabled namespaces are diagnosed before container operations',async()=>{
  const f=fixture();f.files.set('/etc/subgid','somebody_else:100000:65536');f.devices.clear();
  f.files.set('/proc/sys/kernel/unprivileged_userns_clone','0');
  const r=await checkLinuxHost(f.runner,f.host);
  for(const id of ['subgid','render','namespaces'])assert.equal(r.checks?.find(c=>c.id===id)?.status,'error');
});
test('an old NVIDIA encoder driver is a warning, preserving CPU encoding fallback',async()=>{
  const f=fixture();f.devices.add('/dev/nvidiactl');f.executables.add('nvidia-ctk');f.responses.set('nvidia-smi','NVIDIA GTX, 550.90');
  const r=await checkLinuxHost(f.runner,f.host);assert.equal(r.available,true);
  assert.equal(r.checks?.find(c=>c.id==='nvenc')?.status,'warning');
});
test('an old Podman and a root launch have explicit remedies',async()=>{
  const f=fixture();f.host.uid=0;f.responses.set('podman','podman version 4.9.3');
  const r=await checkLinuxHost(f.runner,f.host);assert.match(r.message!,/without sudo/);assert.match(r.message!,/version 5/);
});

test('configured storage validates Podman mappings, monitor and selected network helper',async()=>{
 const f=fixture(),directory=await mkdtemp(join(tmpdir(),'astra-prerequisites-'));
 f.executables.delete('pasta');f.executables.add('slirp4netns');
 f.devices.add('/usr/bin/conmon');f.devices.add('/usr/lib/podman/netavark');
 const info={host:{security:{rootless:true},idMappings:{uidmap:[{container_id:1,size:65536}],gidmap:[{container_id:1,size:65536}]},
  conmon:{path:'/usr/bin/conmon'},networkBackendInfo:{path:'/usr/lib/podman/netavark'},rootlessNetworkCmd:'pasta',pasta:null}};
 const runner:Runner=async(p,a,o)=>a.includes('info')?{code:0,stderr:'',stdout:JSON.stringify(info)}:f.runner(p,a,o);
 try{
  const result=await new PodmanBackend(directory,runner,undefined,f.host).check();
  assert.equal(result.available,false);assert.equal(result.checks?.find(c=>c.id==='configured-network')?.status,'error');
  info.host.idMappings.uidmap=[];
  assert.match((await new PodmanBackend(directory,runner,undefined,f.host).check()).message!,/no usable subordinate/);
 }finally{await rm(directory,{recursive:true,force:true});}
});
