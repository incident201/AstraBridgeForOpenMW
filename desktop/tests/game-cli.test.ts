import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseGame,type Catalog} from '../main/game-cli';
const catalog:Catalog=JSON.parse(readFileSync('resources/game-commands.json','utf8'));
test('game command parsing preserves movement values, booleans and JSON',()=>{
  assert.deepEqual(parseGame(catalog,['move-local','-1.5','--sideways-m','2','--run']).args,
    {under_fire:false,run:true,seconds:30,sideways_m:2,forward_m:-1.5});
  assert.equal(parseGame(catalog,['observe','--no-screenshot']).args.no_screenshot,true);
  assert.equal(parseGame(catalog,['interact','visible_1','--no-adjust-viewpoint']).args.adjust_viewpoint,false);
  assert.deepEqual(parseGame(catalog,['act','{"move":1,"seconds":2}','--request-id','a']).args,{move:1,seconds:2,request_id:'a'});
});
test('required safety limits and invalid options are rejected',()=>{
  assert.throws(()=>parseGame(catalog,['buy','Bread']),/max-total/);
  assert.throws(()=>parseGame(catalog,['act','[]']),/JSON object/);
  assert.throws(()=>parseGame(catalog,['serve']),/Unknown/);
  assert.throws(()=>parseGame(catalog,['read','--all','--search','x']),/only one/);
});

test('aerial controls preserve direction, time budget and operation names',()=>{
  assert.deepEqual(parseGame(catalog,['jump','forward-left','--run','--seconds','0.3']).args,
    {direction:'forward-left',run:true,seconds:0.3});
  const steering=parseGame(catalog,['air-move','back','--seconds','0.4']);
  assert.equal(steering.op,'air_move');
  assert.deepEqual(steering.args,{direction:'back',run:false,seconds:0.4});
  assert.equal(parseGame(catalog,['wait-until','landed']).args.condition,'landed');
  assert.throws(()=>parseGame(catalog,['jump','up']),/direction/);
});

test('knowledge checkpoint JSON remains nested and brief has no payload',()=>{
  const state={goal:'Find the house',next_step:'Inspect the remaining doors',evidence_refs:[]};
  assert.deepEqual(parseGame(catalog,['knowledge','checkpoint',JSON.stringify(state)]).args,
    {action:'checkpoint',checkpoint:state});
  assert.deepEqual(parseGame(catalog,['knowledge','brief']).args,{action:'brief'});
  assert.deepEqual(parseGame(catalog,['knowledge','update','--ref','note_1','--status','done']).args,
    {action:'update',ref:'note_1',status:'done'});
});
