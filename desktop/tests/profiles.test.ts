import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {Core,type Installation} from '../main/core';

test('connecting passes the expected profile to startup before acquiring control',async()=>{
 const core=new Core('/unused');const calls:string[]=[];
 core.start=async(_gpu,profile)=>{calls.push('start');assert.equal(profile,'chosen');throw Error('profile_mismatch');};
 core.api=async()=>{calls.push('connect');};
 await assert.rejects(()=>core.connect('Agent','chosen'),/profile_mismatch/);assert.deepEqual(calls,['start']);
});

test('skill export binds the active profile and keeps its ID independent of its name',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'astra-profile-export-'));
 try{
  await mkdir(join(directory,'skill'));await writeFile(join(directory,'skill/SKILL.md'),'Gameplay instructions');
  const core=new Core(directory,join(directory,'configuration.json'));
  core.ensureDaemon=async()=>({} as Installation);core.profiles=async()=>({active:{id:'profile-id',name:'Playthrough'}});
  const result=await core.exportSkill(join(directory,'export'),'selected.AppImage');
  const metadata=JSON.parse(await readFile(join(directory,'export/installation.json'),'utf8'));
  assert.deepEqual(metadata.profile,{id:'profile-id',name:'Playthrough'});assert.equal(result.profile.id,metadata.profile.id);
  assert.equal(metadata.config,core.configFile);assert.equal(metadata.executable,'selected.AppImage');
 }finally{await rm(directory,{recursive:true,force:true});}
});

test('recording artifacts resolve an active profile host subdirectory without downloading a second copy',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'astra-profile-recording-'));
 try{
  const recordings=join(directory,'recordings'),profile='a'.repeat(32);await mkdir(join(recordings,profile),{recursive:true});
  const file=join(recordings,profile,'record.mp4');await writeFile(file,'existing video');
  const core=new Core(directory);let cancelled=false;
  core.fetch=async()=>new Response(new ReadableStream({cancel(){cancelled=true;}}),{headers:{'X-Astra-Artifact-Kind':'recording','X-Astra-Artifact-Relative-Path':profile+'/record.mp4'}});
  const result=await core.materialize('/v1/artifacts/'+'b'.repeat(32),{storageDirectory:directory,recordingsDirectory:recordings,agentProfile:profile} as Installation);
  assert.equal(result,file);assert.ok(cancelled);
 }finally{await rm(directory,{recursive:true,force:true});}
});
