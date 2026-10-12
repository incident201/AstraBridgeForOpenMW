import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdtemp,readFile,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {Core,type Installation} from '../main/core';

test('save import streams exact host bytes into an explicit or active profile without starting the game',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'astra-save-upload-'));
  const filename=join(directory,'Перед пещерами.omwsave');
  const bytes=Buffer.concat([Buffer.from('TES3'),Buffer.alloc(2*1024*1024,7)]);
  const uploads:{path:string;name:string;data:Buffer}[]=[];
  const server=createServer(async(request,response)=>{
    assert.equal(request.headers.authorization,'Bearer installation-secret');
    let result:any;
    if(request.url==='/v1/runtime/status')result={running:false};
    else if(request.url==='/v1/runtime/profiles')result={active:{id:'active'},profiles:[{id:'active'},{id:'experiment'}]};
    else{
      const chunks:Buffer[]=[];
      for await(const chunk of request)chunks.push(Buffer.from(chunk));
      const data=Buffer.concat(chunks);
      assert.equal(request.headers['content-type'],'application/octet-stream');
      assert.equal(Number(request.headers['content-length']),bytes.length);
      uploads.push({path:request.url!,name:String(request.headers['x-astra-save-filename']),data});
      result={imported:true};
    }
    response.setHeader('Content-Type','application/json');
    response.end(JSON.stringify({ok:true,result}));
  });
  await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve));
  try{
    await writeFile(filename,bytes);
    const config={apiPort:(server.address() as any).port,token:'installation-secret'} as Installation;
    const core=new Core('/unused',join(directory,'installation.json'));
    core.ensureDaemon=async()=>config;
    core.start=async()=>{throw new Error('Import must not start OpenMW');};
    assert.deepEqual(await core.importSave(filename,'experiment'),{imported:true});
    assert.deepEqual(await core.importSave(filename),{imported:true});
    assert.deepEqual(uploads.map(upload=>upload.path),[
      '/v1/runtime/profiles/experiment/saves/import','/v1/runtime/profiles/active/saves/import',
    ]);
    for(const upload of uploads){
      assert.equal(decodeURIComponent(upload.name),'Перед пещерами.omwsave');
      assert.deepEqual(upload.data,bytes);
    }
    assert.deepEqual(await readFile(filename),bytes);
    await assert.rejects(()=>core.importSave(filename,'unknown'),/Profile not found/);
    assert.equal(uploads.length,2);
  }finally{
    await new Promise<void>(resolve=>server.close(()=>resolve()));
    await rm(directory,{recursive:true,force:true});
  }
});

test('invalid files and a running game prevent save uploads',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'astra-save-reject-'));
  try{
    const core=new Core('/unused',join(directory,'installation.json'));
    let started=0;
    core.ensureDaemon=async()=>{started++;return {} as Installation;};
    core.fetch=async()=>{throw new Error('A rejected file must not be uploaded');};
    await assert.rejects(()=>core.importSave(join(directory,'original.ess')),/\.omwsave/);
    const invalid=join(directory,'invalid.omwsave');
    await writeFile(invalid,'not a save');
    await assert.rejects(()=>core.importSave(invalid),/not an OpenMW save/);
    assert.equal(started,0);
    const valid=join(directory,'valid.omwsave');
    await writeFile(valid,'TES3metadata');
    core.api=async()=>({running:true});
    await assert.rejects(()=>core.importSave(valid),/Stop the game/);
  }finally{
    await rm(directory,{recursive:true,force:true});
  }
});

test('save validation failures retain the daemon diagnostic',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'astra-save-error-'));
  try{
    const filename=join(directory,'damaged.omwsave');
    await writeFile(filename,'TES3damaged');
    const core=new Core('/unused',join(directory,'installation.json'));
    core.ensureDaemon=async()=>({} as Installation);
    core.api=async path=>path.endsWith('/status')?{running:false}:{active:{id:'chosen'},profiles:[{id:'chosen'}]};
    core.fetch=async()=>new Response(JSON.stringify({ok:false,error:'invalid_save_file',message:'Damaged record structure'}),{status:409});
    await assert.rejects(()=>core.importSave(filename),(error:any)=>{
      assert.equal(error.message,'Damaged record structure');
      assert.equal(error.details.error,'invalid_save_file');
      return true;
    });
  }finally{
    await rm(directory,{recursive:true,force:true});
  }
});
