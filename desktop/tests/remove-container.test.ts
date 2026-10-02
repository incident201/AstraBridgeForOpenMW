import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {Core} from '../main/core';

test('removing a container retains configuration, volume identities and host files',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'astra-remove-'));let exists=true;const calls:string[]=[];
 const config={name:'astrabridge-fixture',installed:true,backend:'podman',storageDirectory:directory,sourceGame:'/chosen/game',gameMode:'mount',
  gameDirectory:'/chosen/game',recordingsDirectory:join(directory,'recordings'),gameVolume:'astrabridge-game-fixture',stateVolume:'astrabridge-state-fixture',
  agentToken:'obsolete',image:'runtime',digest:'sha256:test'};
 try{
  await mkdir(config.recordingsDirectory);await writeFile(join(config.recordingsDirectory,'keep.mp4'),'recording');
  await writeFile(join(directory,'release.json'),JSON.stringify({version:'test',image:'runtime',digest:config.digest}));
  const path=join(directory,'installation.json');await writeFile(path,JSON.stringify(config));
  const core=new Core(directory,path);
  core.backend=()=>({check:async()=>({available:true,version:'test'}),inspect:async()=>({exists,running:false}),remove:async(name:string)=>{calls.push(name);exists=false;},
    pull:async()=>config.digest,create:async(spec:any)=>{assert.equal(spec.stateVolume,config.stateVolume);assert.equal(spec.gameDirectory,config.gameDirectory);exists=true;}} as any);
  await core.removeContainer();const saved=JSON.parse(await readFile(path,'utf8'));
  assert.deepEqual(calls,[config.name]);assert.equal(saved.stateVolume,config.stateVolume);assert.equal(saved.gameVolume,config.gameVolume);
  assert.equal(saved.agentToken,undefined);assert.equal(saved.phase,'container-removed');
  assert.equal(await readFile(join(config.recordingsDirectory,'keep.mp4'),'utf8'),'recording');
  await core.update();assert.ok(exists);assert.equal(JSON.parse(await readFile(path,'utf8')).phase,'ready');
 }finally{await rm(directory,{recursive:true,force:true});}
});
