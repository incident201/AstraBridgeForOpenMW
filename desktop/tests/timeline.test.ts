import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,appendFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {RecordingTimeline} from '../main/timeline';

test('seeking rewinds comments, action state and clocks without future events',async()=>{
 const root=await mkdtemp(join(tmpdir(),'timeline-'));
 try{
  const path=join(root,'clip.events.jsonl');
  const row=(at:number,fields:any)=>({recording_seconds:at,wall_seconds:10+at,game_seconds:at,wall_active:true,game_active:true,...fields});
  const rows=[row(0,{kind:'snapshot',events:[{id:'prior',kind:'comment',text:'Earlier plan'}]}),
   row(1,{kind:'action',action_id:'move',operation:'move',state:'active'}),
   row(2,{id:'later',kind:'comment',text:'A later discovery'}),
   row(3,{kind:'action',action_id:'move',operation:'move',state:'finished'}),row(4,{kind:'clock'})];
  await writeFile(path,rows.map(r=>JSON.stringify(r)+'\n').join(''));
  const timeline=new RecordingTimeline(path);
  const start=await timeline.at(.5);assert.equal(start.events.length,1);assert.equal(start.clocks.wall_seconds,10.5);
  const middle=await timeline.at(1.5);assert.equal(middle.events.at(-1).state,'active');
  assert.ok(!middle.events.some(e=>e.id==='later'));
  const end=await timeline.at(3.5);assert.ok(end.events.some(e=>e.id==='later'));assert.equal(end.events.at(-1).state,'finished');
  assert.deepEqual(await timeline.at(.5),start);
  await appendFile(path,JSON.stringify(row(5,{id:'live',kind:'comment',text:'New live event'}))+'\n');
  assert.deepEqual(await timeline.at(1.5),middle,'A paused historical position must not show new live messages');
  assert.ok((await timeline.at(5)).events.some(e=>e.id==='live'));
 }finally{await rm(root,{recursive:true,force:true});}
});

test('growing JSONL publishes complete events and checkpoints preserve old active actions',async()=>{
 const root=await mkdtemp(join(tmpdir(),'timeline-'));
 try{
  const path=join(root,'clip.events.jsonl');
  const rows=[{recording_seconds:0,kind:'action',action_id:'long',operation:'approach',state:'active'}];
  for(let i=1;i<300;i++)rows.push({recording_seconds:i,kind:'action',action_id:String(i),operation:'observe',state:'finished'});
  await writeFile(path,rows.map(r=>JSON.stringify(r)+'\n').join(''));
  const timeline=new RecordingTimeline(path);assert.equal((await timeline.at(299)).events.length,5);
  assert.ok((await timeline.at(290)).events.some(e=>e.action_id==='long'&&e.state==='active'));
  const comment=JSON.stringify({recording_seconds:300,kind:'comment',text:'Complete only'});
  await appendFile(path,comment.slice(0,15));assert.equal((await timeline.at(300)).events.length,5);
  await appendFile(path,comment.slice(15)+'\n');assert.equal((await timeline.at(300)).events.length,6);
  assert.equal((await timeline.at(.5)).events.length,1);
  await writeFile(path,JSON.stringify({recording_seconds:0,kind:'comment',text:'Replacement'})+'\n');
  assert.deepEqual((await timeline.at(10)).events.map(e=>e.text),['Replacement']);
 }finally{await rm(root,{recursive:true,force:true});}
});
