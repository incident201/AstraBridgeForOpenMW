import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
const afterPack=createRequire(import.meta.url)('../packaging/after-pack.cjs');

test('AppImage launcher separates an injected Electron flag from GUI and CLI arguments',{skip:process.platform!=='linux'},async()=>{
 const directory=await mkdtemp(join(tmpdir(),'astra launcher '));
 try{
  const binary=join(directory,'astrabridge-desktop');
  await writeFile(binary,'#!/usr/bin/env node\nconsole.log(JSON.stringify({args:process.argv.slice(2),node:process.env.ELECTRON_RUN_AS_NODE??null,resources:process.env.ASTRA_RESOURCES??null}));\n',{mode:0o755});
  await afterPack({electronPlatformName:'linux',appOutDir:directory});
  const run=(args:string[])=>JSON.parse(execFileSync(binary,args,{encoding:'utf8',env:{PATH:process.env.PATH,ELECTRON_RUN_AS_NODE:'stale'}}));
  assert.deepEqual(run([]),{args:[],node:null,resources:null});
  assert.deepEqual(run(['--no-sandbox']),{args:['--no-sandbox'],node:null,resources:null});
  const cli=join(directory,'resources/app.asar/out/cli.cjs');
  const expected={args:[cli,'version'],node:'1',resources:join(directory,'resources/astra')};
  assert.deepEqual(run(['version']),expected);
  assert.deepEqual(run(['--no-sandbox','version']),expected);
  const args=['--config','profile with spaces.json','game','act','{"seconds":2,"move":1}'];
  assert.deepEqual(run(['--no-sandbox',...args]).args,[cli,...args]);
 }finally{await rm(directory,{recursive:true,force:true});}
});

test('AppImage identifies missing Electron libraries before attempting GUI or CLI startup',{skip:process.platform!=='linux'},async()=>{
 const directory=await mkdtemp(join(tmpdir(),'astra missing libs '));
 try{
  const binary=join(directory,'astrabridge-desktop');
  await writeFile(binary,'#!/bin/sh\necho should-not-start\n',{mode:0o755});
  await writeFile(join(directory,'ldd'),'#!/bin/sh\necho "libnss3.so => not found"\necho "libgtk-3.so.0 => not found"\n',{mode:0o755});
  await afterPack({electronPlatformName:'linux',appOutDir:directory});
  for(const args of [[],['version']]){
   assert.throws(()=>execFileSync(binary,args,{encoding:'utf8',stdio:'pipe',env:{PATH:directory+':'+process.env.PATH}}),
    (error:any)=>error.status===1&&error.stderr.includes('libnss3.so')&&error.stderr.includes('libgtk-3.so.0')&&!error.stdout.includes('should-not-start'));
  }
 }finally{await rm(directory,{recursive:true,force:true});}
});
