import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {Core} from '../main/core';
import {StopSessionRequest} from '../main/stop-session';

for(const mode of ['saved','failed','offline'] as const)test('Stop session handles '+mode+' without implicit data loss',async()=>{
 const root=await mkdtemp(join(tmpdir(),'save-stop-'));let stops=0,prepared=0;
 try{
  const core=new Core(root,join(root,'installation.json'));
  const config:any={name:'test',agentToken:'token'};core.configured=async()=>config;
  core.backend=()=>({inspect:async()=>({running:true})} as any);
  core.stop=async()=>{stops++;return {closed:true} as any;};
  core.api=async path=>{
   if(path.endsWith('/status'))return {running:true};
   if(path.endsWith('/cancel-stop'))return {cancelled:true};
   prepared++;if(mode==='offline')throw Error('unreachable');
   return {token:'stop-token',save:{status:mode,reason:'save_unavailable'}};
  };
  if(mode==='saved'){assert.equal((await core.stopSession() as any).closed,true);assert.equal(stops,1);}
  else{
   await assert.rejects(()=>core.stopSession(),(e:any)=>e.details.error==='save_before_stop_failed'&&e.details.needs_confirmation);
   assert.equal(stops,0);assert.equal(JSON.parse(await readFile(core.configFile,'utf8')).lastStop.reason,'user_requested_stop');
   await core.cancelSessionStop();assert.equal(JSON.parse(await readFile(core.configFile,'utf8')).lastStop,undefined);
  }
  assert.equal(prepared,1);
 }finally{await rm(root,{recursive:true,force:true});}
});
for(const choice of [false,true])test('save failure confirmation '+(choice?'discards':'cancels'),async()=>{
 let discarded=0,cancelled=0,dialogs=0;
 const request=new StopSessionRequest(async()=>{throw Object.assign(Error('save failed'),{details:{error:'save_before_stop_failed',reason:'save_unavailable',token:'token'}});},
  async reason=>{assert.equal(reason,'save_unavailable');dialogs++;return choice;},async()=>{discarded++;return {stopped:true};},async token=>{assert.equal(token,'token');cancelled++;});
 const result=await request.request();assert.equal(discarded,choice?1:0);assert.equal(cancelled,choice?0:1);assert.equal(dialogs,1);
 assert.equal(Boolean(result.cancelled),!choice);
});
test('concurrent Stop and close share one save and confirmation',async()=>{
 let attempts=0,dialogs=0,finish!:(value:any)=>void;const wait=new Promise(r=>finish=r);
 const request=new StopSessionRequest(async()=>{attempts++;await wait;throw Object.assign(Error('save'),{details:{error:'save_before_stop_failed'}});},async()=>{dialogs++;return false;},async()=>{},async()=>{});
 const first=request.request(),second=request.request();assert.equal(first,second);finish({});await first;assert.equal(attempts,1);assert.equal(dialogs,1);
});
