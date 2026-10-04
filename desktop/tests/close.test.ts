import test from 'node:test';
import assert from 'node:assert/strict';
import {CloseRequest} from '../main/close';

test('closing a stopped runtime needs no question or stop',async()=>{
  const close=new CloseRequest(async()=>false,async()=>{throw Error('unexpected question');},async()=>{throw Error('unexpected stop');},async()=>{});
  assert.equal(await close.request(),true);
});
test('cancel and keep-running never stop the runtime',async()=>{
  for(const choice of ['cancel','keep'] as const){
    let stopped=0;const close=new CloseRequest(async()=>true,async()=>choice,async()=>{stopped++;},async()=>{});
    assert.equal(await close.request(),choice==='keep');assert.equal(stopped,0);
  }
});
test('repeated close events share a dialog and await the same graceful stop',async()=>{
  let dialogs=0,stops=0,finish!:()=>void;
  const stopped=new Promise<void>(resolve=>finish=resolve);
  const close=new CloseRequest(async()=>true,async()=>{dialogs++;return 'stop';},async()=>{stops++;await stopped;},async()=>{});
  const one=close.request(),two=close.request();assert.equal(one,two);
  await new Promise(resolve=>setImmediate(resolve));assert.equal(dialogs,1);assert.equal(stops,1);
  finish();assert.equal(await one,true);
});
test('a failed stop keeps the window open and reports the error',async()=>{
  const errors:unknown[]=[];const close=new CloseRequest(async()=>true,async()=> 'stop',async()=>{throw Error('stop failed');},async error=>{errors.push(error);});
  assert.equal(await close.request(),false);assert.equal(errors.length,1);
});

test('cancelling stop after a failed save keeps Desktop open',async()=>{
 const close=new CloseRequest(async()=>true,async()=> 'stop',async()=>({cancelled:true}),async()=>{throw Error('Cancel is not an error');});
 assert.equal(await close.request(),false);
});
