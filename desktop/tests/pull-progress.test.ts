import test from 'node:test';
import assert from 'node:assert/strict';
import {PullProgress,type PullStatus} from '../main/runtime/PullProgress';
import {run} from '../main/runtime/RuntimeBackend';
const layer=(id:string,size:number)=>({digest:'sha256:'+id.repeat(64),size});

test('parallel layer counters distinguish downloads from reused layers and survive split ANSI chunks',()=>{
 const events:PullStatus[]=[];const p=new PullProgress('image',value=>{if(typeof value!=='string'&&value.type==='transfer')events.push(value);},[layer('a',1024**2),layer('b',2*1024**2)]);
 try{
  p.feed('\x1b[');p.feed('2KCopying blob aaaaaaaaaaaa skipped: already exists\r\n');
  p.feed('Copying blob bbbbbbbbbbbb [====>] 1.0 MiB / 2.0 MiB | 1.0 MiB/s\r\n');
  assert.equal(p.status().received,1024**2);assert.equal(p.status().total,2*1024**2);assert.equal(p.status().reused,1024**2);
  p.feed('Copying blob bbbbbbbbbbbb done\r\nWriting manifest to image destination\n');
  assert.equal(p.status().completed,2);assert.equal(p.status().phase,'unpacking');
 }finally{p.finish(true);}
 assert.equal(events.at(-1)?.phase,'complete');
});
test('unknown size and failed downloads remain explicit',()=>{
 const p=new PullProgress('image');p.feed('Connecting to registry\n');
 assert.equal(p.status().total,null);p.finish(false);assert.equal(p.status().phase,'failed');
});
test('terminal runner preserves argument boundaries and child exit status',{skip:process.platform!=='linux'},async()=>{
 const literal="spaces ; $(echo wrong) ' \"";
 const result=await run(process.execPath,['-e','console.log(process.stdout.isTTY,JSON.stringify(process.argv[1]));process.exit(7)',literal],{terminal:true});
 assert.equal(result.code,7);assert.ok(result.stdout.includes('true '+JSON.stringify(literal)));
});

test('terminal download timeout terminates its child',{skip:process.platform!=='linux'},async()=>{
 const {mkdtemp,readFile,rm}=await import('node:fs/promises');const {tmpdir}=await import('node:os');const {join}=await import('node:path');
 const root=await mkdtemp(join(tmpdir(),'pull-timeout-')),file=join(root,'pid');let pid:number|undefined;
 try{
  await assert.rejects(()=>run(process.execPath,['-e','require("fs").writeFileSync(process.argv[1],String(process.pid));setInterval(()=>{},1000)',file],{terminal:true,timeout:1000}),/timed out/);
  pid=Number(await readFile(file,'utf8'));await new Promise(r=>setTimeout(r,500));
  const state=await readFile(`/proc/${pid}/stat`,'utf8').catch(()=>'');
  assert.ok(!state||state.split(') ')[1].startsWith('Z'),'Timeout left its download process running');
 }finally{if(pid)try{process.kill(pid,'SIGKILL');}catch{}await rm(root,{recursive:true,force:true});}
});
