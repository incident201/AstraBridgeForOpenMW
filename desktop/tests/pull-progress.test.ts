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
 const result=await run(process.execPath,['-e','process.stdout.write(JSON.stringify({tty:process.stdout.isTTY,arg:process.argv[1]}));process.exit(7)',literal],{terminal:true});
 assert.equal(result.code,7);assert.deepEqual(JSON.parse(result.stdout.trim()),{tty:true,arg:literal});
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

test('UTF-8 output and progress survive chunks split within a multibyte character',async()=>{
 const chunks:string[]=[];
 const result=await run(process.execPath,['-e',
  'const text=Buffer.from("Привет 🌍");let i=0;const next=()=>{if(i===text.length)return;process.stdout.write(text.subarray(i,i+1));process.stderr.write(text.subarray(i,i+1));i++;setTimeout(next,3)};next();'],
  {progress:value=>{if(typeof value==='string')chunks.push(value);}});
 assert.equal(result.stdout,'Привет 🌍');assert.equal(result.stderr,'Привет 🌍');
 assert.equal(chunks.join('').includes('\ufffd'),false);
});

test('terminal timeout kills grandchildren that ignore normal shutdown',{skip:process.platform!=='linux'},async()=>{
 const {mkdtemp,readFile,rm}=await import('node:fs/promises');const {tmpdir}=await import('node:os');const {join}=await import('node:path');
 const root=await mkdtemp(join(tmpdir(),'pull-tree-')),file=join(root,'pid');let pid:number|undefined;
 try{
  const descendant='process.on("SIGTERM",()=>{});process.on("SIGHUP",()=>{});require("fs").writeFileSync(process.argv[1],String(process.pid));setInterval(()=>{},1000)';
  const parent='require("child_process").spawn(process.execPath,["-e",process.argv[1],process.argv[2]],{stdio:"inherit"});process.on("SIGTERM",()=>{});process.on("SIGHUP",()=>{});setInterval(()=>{},1000)';
  await assert.rejects(()=>run(process.execPath,['-e',parent,descendant,file],{terminal:true,timeout:1000}),/timed out/);
  pid=Number(await readFile(file,'utf8'));
  const state=await readFile(`/proc/${pid}/stat`,'utf8').catch(()=>'');
  assert.ok(!state||['Z','X'].includes(state.split(') ')[1][0]),'Timeout left a PTY grandchild running');
 }finally{if(pid)try{process.kill(pid,'SIGKILL');}catch{}await rm(root,{recursive:true,force:true});}
});

test('failed command input terminates its process tree and retains the original error',{skip:process.platform!=='linux'},async()=>{
 const {PassThrough}=await import('node:stream');
 const input=new PassThrough();
 const result=run(process.execPath,['-e','process.on("SIGTERM",()=>{});setInterval(()=>{},1000)'],{input,timeout:5000});
 setTimeout(()=>input.destroy(Error('input stream failed')),150);
 await assert.rejects(()=>result,/input stream failed/);
 assert.equal(input.listenerCount('error'),0);
});
