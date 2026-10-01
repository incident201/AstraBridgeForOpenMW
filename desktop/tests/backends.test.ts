import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {PodmanBackend} from '../main/runtime/PodmanBackend';
import {WslContainerBackend} from '../main/runtime/WslContainerBackend';
import type {RuntimeSpec,Runner} from '../main/runtime/RuntimeBackend';
const spec:RuntimeSpec={name:'astrabridge-test',image:'ghcr.io/incident201/astrabridge-runtime@sha256:abc',digest:'sha256:abc',
  token:'x'.repeat(40),gameVolume:'astrabridge-game-test',stateVolume:'astrabridge-state-test',apiPort:18770,rtcPort:18771,mode:'production',gpuDevices:['/dev/dri/renderD128'],recordingsDirectory:'/chosen/recordings'};
test('Linux manages persistent rootless resources and publishes only loopback',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'astra-backend-'));const calls:string[][]=[];
  const runner:Runner=async(program,args)=>{calls.push([program,...args]);return {code:0,stdout:'',stderr:''};};
  try{
    const backend=new PodmanBackend(directory,runner);await backend.create(spec);await backend.start(spec.name);await backend.stop(spec.name);
    const create=calls[0];assert.ok(create.includes('create'));assert.ok(create.includes('127.0.0.1:18770:18770/tcp'));
    assert.ok(create.includes('--read-only'));assert.ok(create.includes('--cap-drop=ALL'));
    assert.ok(create.some(arg=>arg.includes('dst=/managed-game,ro=true')));
    assert.ok(create.includes('type=bind,src=/chosen/recordings,dst=/data/recordings'));
    assert.ok(!create.some(arg=>arg.includes('--privileged')||arg.includes('--pid=host')||arg.includes('podman.sock')));
    assert.ok(!calls.slice(1).some(args=>args.includes('rm')||args.includes('create')));
  }finally{await rm(directory,{recursive:true,force:true});}
});
test('Windows uses wslc directly with GPU access and managed volumes',async()=>{
  const calls:string[][]=[];const runner:Runner=async(program,args)=>{calls.push([program,...args]);return {code:0,stdout:'',stderr:''};};
  const backend=new WslContainerBackend(runner);await backend.create(spec);await backend.start(spec.name);await backend.stop(spec.name);
  assert.ok(calls.every(args=>args[0]==='wslc.exe'));
  assert.ok(calls[0].includes('--gpus'));assert.ok(calls[0].includes('LIBVA_DRIVER_NAME=d3d12'));
  assert.ok(!calls.flat().some(arg=>['podman','docker','ubuntu','--distribution'].includes(arg)));
  await assert.rejects(()=>backend.create({...spec,name:'unmanaged-container'}),/Invalid managed resource/);
});
test('Linux binds the selected host game read-only and passes NVIDIA CDI without host display',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'astra-backend-'));const calls:string[][]=[];
  const runner:Runner=async(program,args)=>{calls.push([program,...args]);return {code:0,stdout:'',stderr:''};};
  try{
    await new PodmanBackend(directory,runner).create({...spec,gameDirectory:'/games/Morrowind',gpuDevices:['/dev/dri/renderD128','nvidia.com/gpu=all']});
    const args=calls[0];assert.ok(args.includes('type=bind,src=/games/Morrowind,dst=/managed-game/content,ro=true'));
    assert.ok(args.includes('nvidia.com/gpu=all'));assert.ok(args.includes('NVIDIA_DRIVER_CAPABILITIES=graphics,video,utility,compute'));
    assert.equal(args[args.indexOf('--runtime')+1],'crun');
    assert.ok(!args.some(arg=>arg.includes('/tmp/.X11-unix')||arg.includes('DISPLAY=')||arg.includes('/run/user/')));
  }finally{await rm(directory,{recursive:true,force:true});}
});
