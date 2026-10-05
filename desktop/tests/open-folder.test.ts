import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm,stat,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';
import {openFolder} from '../main/open-folder';
import {Core} from '../main/core';

test('Linux opens an encoded file URL and never awaits the broken OpenPath',async()=>{
  const directory="/recordings/Мой профиль #1 % ' & $(text)";
  let called=false;
  await openFolder(directory,{
    openPath:async()=>{assert.fail('Linux must not call shell.openPath');},
    openExternal:async url=>{called=true;assert.equal(new URL(url).protocol,'file:');assert.equal(fileURLToPath(url),directory);assert.equal(new URL(url).hash,'');},
  },{platform:'linux'});
  assert.ok(called);
});

test('Windows keeps native directory and UNC handling',async()=>{
  const directory='\\\\server\\Recordings\\Profile #1';
  await openFolder(directory,{
    openPath:async path=>{assert.equal(path,directory);return '';},
    openExternal:async()=>assert.fail('Windows uses the native path'),
  },{platform:'win32'});
});

test('system launch failures retain diagnostics and the folder path',async()=>{
  for(const platform of ['linux','win32']){
    await assert.rejects(()=>openFolder('/records',{
      openPath:async()=> 'No default application',
      openExternal:async()=>{throw Error('No default application');},
    },{platform}),/Could not open folder "\/records": No default application/);
  }
});

test('a dropped completion callback returns a bounded useful error',async()=>{
  await assert.rejects(()=>openFolder('/records',{
    openPath:()=>new Promise(()=>{}),openExternal:()=>new Promise(()=>{}),
  },{platform:'linux',timeoutMs:20}),/Could not open folder.*system did not respond/);
});

test('opening the recordings directory needs no container and preserves its files',async()=>{
  const root=await mkdtemp(join(tmpdir(),'astra-folder-'));
  try{
    const directory=join(root,'Records with spaces');
    const core=new Core(root,join(root,'installation.json'));
    core.configured=async()=>({recordingsDirectory:directory} as any);
    core.backend=()=>assert.fail('Opening a host folder must not inspect/start a container');
    core.api=async()=>assert.fail('Opening a host folder must not call the runtime');
    assert.equal(await core.recordingsFolder(),directory);assert.ok((await stat(directory)).isDirectory());
    await writeFile(join(directory,'keep.mp4'),'existing recording');
    await openFolder(await core.recordingsFolder(),{
      openPath:async()=>assert.fail('Linux path'),
      openExternal:async url=>assert.equal(fileURLToPath(url),directory),
    },{platform:'linux'});
    assert.equal(await readFile(join(directory,'keep.mp4'),'utf8'),'existing recording');
  }finally{await rm(root,{recursive:true,force:true});}
});
