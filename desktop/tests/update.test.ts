import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {Core,type Installation} from '../main/core';

const digest=(char:string)=>'sha256:'+char.repeat(64);
async function fixture(){
 const directory=await mkdtemp(join(tmpdir(),'astra-update-'));const configFile=join(directory,'installation.json');
 const old:Installation={name:'astrabridge-test',image:'localhost/runtime:old@'+digest('a'),digest:digest('a'),version:'1.0.0',installed:true,
  backend:'podman',storageDirectory:directory,sourceGame:'/game',gameMode:'mount',gameDirectory:'/game',recordingsDirectory:'/recordings',
  gameVolume:'astrabridge-game-test',stateVolume:'astrabridge-state-test',mode:'production',token:'private',gameImported:false,apiPort:18770,rtcPort:18771,
  previous:{image:'localhost/runtime:older@'+digest('c'),digest:digest('c'),version:'0.9.0',snapshot:'update-previous',created:1}};
 const release={version:'2.0.0',image:'localhost/runtime:new',digest:digest('b'),runtime_api:2,game_api:1};
 await writeFile(configFile,JSON.stringify(old));await writeFile(join(directory,'release.json'),JSON.stringify(release));
 const state={exists:true,running:true,game:false,image:old.image,data:'saved progress',failReady:false,failBackup:false,failCleanup:false};
 const backups=new Map([['update-previous','earlier progress']]);const calls:string[]=[];
 const backend={
  inspect:async()=>({exists:state.exists,running:state.running,image:state.image}),
  pull:async()=>{calls.push('pull');assert.ok(state.exists,'Old container must exist during download');return release.digest;},
  start:async()=>{calls.push('start');state.running=true;},stop:async()=>{calls.push('stop');state.running=false;state.game=false;},
  remove:async()=>{calls.push('remove');assert.equal(state.running,false);state.exists=false;},
  create:async(config:Installation)=>{calls.push('create');assert.equal(state.exists,false);assert.equal(config.stateVolume,old.stateVolume);
   assert.equal(config.gameDirectory,old.gameDirectory);assert.equal(config.recordingsDirectory,old.recordingsDirectory);
   state.exists=true;state.image=config.image;if(config.digest===release.digest)state.data='migrated progress';},
  backup:async(_image:string,_volume:string,id:string)=>{calls.push('backup');assert.equal(state.running,false);if(state.failBackup)throw Error('disk full');backups.set(id,state.data);},
  restore:async(_image:string,_volume:string,id:string)=>{calls.push('restore');state.data=backups.get(id)!;},
  pruneBackups:async(_image:string,_volume:string,keep:string)=>{calls.push('prune');if(state.failCleanup)throw Error('busy');for(const id of backups.keys())if(id!==keep)backups.delete(id);},
  removeImage:async(image:string)=>{calls.push('image-rm');assert.equal(image,old.previous!.image);if(state.failCleanup)throw Error('in use');}
 };
 const core=new Core(directory,configFile);core.backend=()=>backend as any;
 core.api=async(path:string)=>{
  if(path==='/v1/runtime/status')return {owner:{mode:'idle'},running:state.game};
  if(path==='/health')return {runtime_api:state.image===old.image?1:state.failReady?99:2,game_api:1,environment:{project_version:state.image===old.image?'1.0.0':'2.0.0'}};
  if(path==='/v1/runtime/engine/stop'){state.game=false;return {};}
  if(path==='/v1/runtime/engine/start'){calls.push('game-start');state.game=true;return {};}
  throw Error(path);
 };
 return {core,old,release,state,backups,calls,configFile,read:async()=>JSON.parse(await readFile(configFile,'utf8')) as Installation,
  close:()=>rm(directory,{recursive:true,force:true})};
}

test('update retains one recovery image/snapshot and keeps game-stopped state',async()=>{
 const f=await fixture();try{
  await f.core.update();const config=await f.read();
  assert.equal(config.digest,f.release.digest);assert.equal(config.previous?.digest,f.old.digest);assert.equal(config.transaction,undefined);
  assert.equal(f.backups.size,1);assert.equal(f.backups.get(config.previous!.snapshot),'saved progress');
  assert.equal(f.state.data,'migrated progress');assert.equal(f.state.running,true);assert.equal(f.state.game,false);
  assert.ok(f.calls.indexOf('backup')<f.calls.indexOf('remove'));assert.ok(f.calls.indexOf('prune')>f.calls.lastIndexOf('start'));
  assert.ok(!f.calls.includes('game-start'));
 }finally{await f.close();}
});
test('failed new runtime restores saved data and old API even across an API version change',async()=>{
 const f=await fixture();try{
  f.state.failReady=true;f.state.game=true;
  await assert.rejects(()=>f.core.update(),/previous runtime and saved data were restored/);
  const config=await f.read();assert.equal(config.digest,f.old.digest);assert.equal(config.transaction,undefined);
  assert.equal(f.state.data,'saved progress');assert.equal(f.state.image,f.old.image);assert.equal(f.state.game,true);
  assert.ok(!f.calls.includes('prune')&&!f.calls.includes('image-rm'));
 }finally{await f.close();}
});
test('backup failure never removes the old container or its data',async()=>{
 const f=await fixture();try{f.state.failBackup=true;
  await assert.rejects(()=>f.core.update(),/previous runtime/);
  assert.equal(f.state.data,'saved progress');assert.ok(!f.calls.includes('remove'));assert.equal(f.state.running,true);
 }finally{await f.close();}
});
test('interrupted replacement recovers from the persisted transaction before downloading again',async()=>{
 const f=await fixture();try{
  f.backups.set('update-interrupted','saved progress');f.state.image='new-partial';f.state.data='partial migration';
  await writeFile(f.configFile,JSON.stringify({...f.old,transaction:{before:f.old,snapshot:'update-interrupted',backedUp:true,replacing:true,wasRunning:true,gameWasRunning:false,api:{runtime_api:1,game_api:1}}}));
  await assert.rejects(()=>f.core.ensureDaemon(),/Recover/);await f.core.update();
  assert.equal(f.state.data,'saved progress');assert.equal(f.state.image,f.old.image);assert.ok(!f.calls.includes('pull'));
  assert.equal((await f.read()).transaction,undefined);
 }finally{await f.close();}
});
test('cleanup failure does not roll back a healthy upgrade; retry remains scoped',async()=>{
 const f=await fixture();try{f.state.failCleanup=true;await f.core.update();
  assert.equal((await f.read()).digest,f.release.digest);assert.equal((await f.read()).cleanupPending,true);
  f.state.failCleanup=false;await f.core.update();assert.equal((await f.read()).cleanupPending,false);assert.equal(f.backups.size,1);
 }finally{await f.close();}
});
test('an older Desktop cannot implicitly downgrade saved data',async()=>{
 const f=await fixture();try{
  await writeFile(f.configFile,JSON.stringify({...f.old,version:'3.0.0'}));
  await assert.rejects(()=>f.core.update(),/older than/);assert.deepEqual(f.calls,[]);assert.equal(f.state.data,'saved progress');
 }finally{await f.close();}
});
