import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,rm,symlink,realpath} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {Recordings} from '../main/recordings';
import {gameDataDirectory} from '../main/game-data';
import {localArtifact} from '../main/local-artifact';

test('offline video serves seekable ranges and full exports',async()=>{
 const root=await mkdtemp(join(tmpdir(),'video-range-'));
 try{
  const file=join(root,'video.mp4');await writeFile(file,'0123456789');
  const middle=await localArtifact(file,'bytes=3-6');assert.equal(middle.status,206);
  assert.equal(middle.headers.get('Content-Range'),'bytes 3-6/10');assert.equal(await middle.text(),'3456');
  assert.equal(await (await localArtifact(file,'bytes=-3')).text(),'789');
  assert.equal(await (await localArtifact(file,'bytes=8-')).text(),'89');
  assert.equal((await localArtifact(file,'bytes=10-')).status,416);
  assert.equal(await (await localArtifact(file)).text(),'0123456789');
 }finally{await rm(root,{recursive:true,force:true});}
});

test('host recordings include all profiles and sidecars without runtime access',async()=>{
 const root=await mkdtemp(join(tmpdir(),'recordings-'));
 try{
  const profile='b'.repeat(32);await mkdir(join(root,profile));
  await writeFile(join(root,'legacy.mp4'),'video');await writeFile(join(root,profile,'Journey.mp4'),'video');
  await writeFile(join(root,profile,'Journey.context.json'),JSON.stringify({profile:{id:profile,name:'Journey'}}));
  await writeFile(join(root,profile,'Journey.events.jsonl'),'{}\n');await writeFile(join(root,'hidden.finalizing.mp4'),'partial');
  const recordings=new Recordings(),rows=await recordings.list(root);
  assert.equal(rows.length,2);const row=rows.find(r=>r.profile_id===profile)!;
  assert.equal(row.profile_name,'Journey');assert.ok(row.events);
  assert.equal(await recordings.path(row.video.split('/').pop()!),await realpath(join(root,profile,'Journey.mp4')));
  assert.equal(await recordings.path('unregistered'),null);
 }finally{await rm(root,{recursive:true,force:true});}
});

test('recording artifact cannot follow a replaced file outside the recordings folder',{skip:process.platform==='win32'},async()=>{
 const root=await mkdtemp(join(tmpdir(),'recordings-'));
 try{
  const directory=join(root,'videos');await mkdir(directory);
  const file=join(directory,'x.mp4');await writeFile(file,'safe');await writeFile(join(root,'private'),'secret');
  const recordings=new Recordings(),[row]=await recordings.list(directory);
  await rm(file);await symlink(join(root,'private'),file);
  await assert.rejects(()=>recordings.path(row.video.split('/').pop()!),/outside/);
 }finally{await rm(root,{recursive:true,force:true});}
});

test('game folder selection detects case, direct data folders and explicit custom layouts',async()=>{
 const root=await mkdtemp(join(tmpdir(),'game-layout-'));
 try{
  await mkdir(join(root,'data files'));await writeFile(join(root,'data files/Morrowind.esm'),'');
  assert.equal(await gameDataDirectory(root),'data files');
  assert.equal(await gameDataDirectory(join(root,'data files')),'.');
  await mkdir(join(root,'custom'));assert.equal(await gameDataDirectory(root,'custom'),'custom');
  await assert.rejects(()=>gameDataDirectory(root,'..'),/inside/);
  await assert.rejects(()=>gameDataDirectory(join(root,'custom')),/Select/);
 }finally{await rm(root,{recursive:true,force:true});}
});
