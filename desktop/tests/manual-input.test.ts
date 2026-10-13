import test from 'node:test';
import assert from 'node:assert/strict';
import {MouseMotion,mouseMotion} from '../frontend/manual-input';

const video={videoWidth:1920,videoHeight:1080,getBoundingClientRect:()=>({left:0,top:0,width:960,height:540})} as HTMLVideoElement;
const move={clientX:900,clientY:500,movementX:2,movementY:-1} as MouseEvent;

test('gameplay uses small physical deltas, never scaled screen positions',()=>{
  assert.deepEqual(mouseMotion(video,move,'Gameplay'),{type:'relative',x:2,y:-1});
  assert.deepEqual(mouseMotion(video,move,undefined),{type:'relative',x:2,y:-1});
});

test('interface cursor maps the pointer to the game image',()=>{
  assert.deepEqual(mouseMotion(video,move,'Interface'),{type:'pointer',x:900/960,y:500/540});
});

test('high-rate mouse input preserves total displacement and release discards pending motion',()=>{
  let callback:FrameRequestCallback=()=>{},scheduled=0,cancelled=0;
  const events:any[]=[];
  const motion=new MouseMotion(event=>events.push(event),fn=>{callback=fn;return ++scheduled;},()=>cancelled++);
  for(let i=0;i<1000;i++)motion.push({type:'relative',x:1,y:-1});
  assert.equal(scheduled,1);
  callback(0);
  assert.deepEqual(events,[{type:'relative',x:1000,y:-1000}]);
  motion.push({type:'pointer',x:.1,y:.2});
  motion.push({type:'pointer',x:.8,y:.9});
  callback(0);
  assert.deepEqual(events[1],{type:'pointer',x:.8,y:.9});
  motion.push({type:'relative',x:8,y:4});
  motion.clear();callback(0);
  assert.equal(cancelled,1);assert.equal(events.length,2);
});
