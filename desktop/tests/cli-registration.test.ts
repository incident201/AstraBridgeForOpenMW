import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm,access} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,delimiter} from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {CliRegistration} from '../main/cli-registration';
import {Core} from '../main/core';
const exec=promisify(execFile);
async function fixture(){
 const root=await mkdtemp(join(tmpdir(),'astra-cli-'));const bin=join(root,'bin'),config=join(root,"Мой профиль 'quoted'.json");
 await mkdir(bin);await writeFile(config,'{}');
 const script=join(root,'app.cjs');await writeFile(script,`const args=process.argv.slice(2);const c=args.indexOf('--config');console.log(JSON.stringify({application:process.env.APPLICATION,args,envConfig:process.env.ASTRA_CONFIG,config:c<0?process.env.ASTRA_CONFIG:args[c+1]}));if(args[0]==='fail')process.exit(17);`);
 const applications=[];
 for(const version of ['old','new']){
  const p=join(root,`Приложение ${version} ' $(echo wrong).AppImage`);
  const q=(s:string)=>"'"+s.replaceAll("'","'\"'\"'")+"'";
  await writeFile(p,`#!/bin/sh\nexport APPLICATION=${version}\nexec ${q(process.execPath)} ${q(script)} "$@"\n`,{mode:0o755});applications.push(p);
 }
 const cli=new CliRegistration(root,{platform:'linux',binDirectory:bin,searchPath:()=>bin+delimiter+process.env.PATH});
 return {root,bin,config,cli,old:applications[0],next:applications[1],close:()=>rm(root,{recursive:true,force:true})};
}
test('registered command works across shells and preserves arguments, config and exit status',{skip:process.platform!=='linux'},async()=>{
 const f=await fixture();try{
  const installed=await f.cli.install(f.old,f.config,'installation','1','digest-1');assert.ok(installed.pathReady);
  const env={...process.env,PATH:f.bin+delimiter+process.env.PATH};
  for(const cwd of [f.root,f.bin]){
   const result=await exec('/bin/sh',['-c','astrabridge game observe'],{env,cwd});const data=JSON.parse(result.stdout);
   assert.deepEqual(data.args,['game','observe']);assert.equal(data.config,f.config);assert.equal(data.application,'old');
  }
  const args=['game','comment','quotes " ; $() \\ кириллица'];
  assert.deepEqual(JSON.parse((await exec(f.cli.executable,args,{env})).stdout).args,args);
  assert.deepEqual(JSON.parse((await exec(f.cli.executable,[],{env})).stdout).args,[],'No arguments must still open the application GUI');
  assert.equal(JSON.parse((await exec(f.cli.executable,['--config','chosen.json','status'],{env})).stdout).config,'chosen.json');
  await assert.rejects(()=>exec(f.cli.executable,['fail'],{env}),(e:any)=>e.code===17);
  await f.cli.refresh(f.next,f.config,'installation','2','digest-2');
  assert.equal(JSON.parse((await exec(f.cli.executable,['version'],{env})).stdout).application,'new');
  await rm(f.next);assert.equal((await f.cli.status(f.config)).targetAvailable,false);
  await assert.rejects(()=>exec(f.cli.executable,['version'],{env}),(e:any)=>e.code===127&&e.stderr.includes('application is missing'));
 }finally{await f.close();}
});
test('only matching installations refresh or remove the command',async()=>{
 const f=await fixture();try{
  await f.cli.install(f.old,f.config,'installation','1','a');const original=await readFile(f.cli.executable);
  assert.equal(await f.cli.refresh(f.next,f.config,'other-installation','2','b'),false);
  assert.equal(await f.cli.refresh(f.next,join(f.root,'another.json'),'installation','2','b'),false);
  assert.deepEqual(await readFile(f.cli.executable),original);
  assert.equal((await f.cli.uninstall(join(f.root,'another.json'))).removed,false);
  assert.equal((await f.cli.uninstall(f.config)).removed,true);await assert.rejects(()=>access(f.cli.executable));
 }finally{await f.close();}
});
test('foreign, shadowing and modified commands are never overwritten or deleted',async()=>{
 const f=await fixture();try{
  await writeFile(f.cli.executable,'foreign',{mode:0o755});
  await assert.rejects(()=>f.cli.install(f.old,f.config,'installation','1','a'),/Another file/);
  await assert.rejects(()=>f.cli.uninstall(f.config));assert.equal(await readFile(f.cli.executable,'utf8'),'foreign');await rm(f.cli.executable);
  const other=join(f.root,'other');await mkdir(other);await writeFile(join(other,'astrabridge'),'foreign',{mode:0o755});
  const shadowed=new CliRegistration(f.root,{platform:'linux',binDirectory:f.bin,searchPath:()=>other});
  await assert.rejects(()=>shadowed.install(f.old,f.config,'installation','1','a'),/already in PATH/);
  await f.cli.install(f.old,f.config,'installation','1','a');await writeFile(f.cli.executable,(await readFile(f.cli.executable,'utf8'))+'# manual edit\n');
  await assert.rejects(()=>f.cli.refresh(f.next,f.config,'installation','2','b'),/modified/);
  await assert.rejects(()=>f.cli.uninstall(f.config),/modified/);
 }finally{await f.close();}
});
test('exports retain the stable executable when the application is replaced',async()=>{
 const f=await fixture();try{
  await mkdir(join(f.root,'skill'));await writeFile(join(f.root,'skill/SKILL.md'),'instructions');
  const core=new Core(f.root,f.config,undefined,{cli:f.cli,executable:f.old});
  core.configured=async()=>({name:'installation',installed:true,digest:'a'} as any);core.load=core.configured;
  core.release=async()=>({version:'1',digest:'a'} as any);
  await core.exportSkill(join(f.root,'not-enabled'));
  assert.deepEqual(JSON.parse(await readFile(join(f.root,'not-enabled/installation.json'),'utf8')),{executable:f.old,config:f.config});
  assert.equal((await f.cli.status()).enabled,false,'Export must not implicitly install a command');
  await core.installCli();await core.exportSkill(join(f.root,'export'));
  const before=await readFile(join(f.root,'export/installation.json'));
  const metadata=JSON.parse(before.toString());assert.equal(metadata.command,'astrabridge');assert.equal(metadata.executable,f.cli.executable);assert.equal(metadata.profile,undefined);
  await f.cli.refresh(f.next,f.config,'installation','2','b');assert.deepEqual(await readFile(join(f.root,'export/installation.json')),before);
 }finally{await f.close();}
});
test('AppImage private PATH entry is ignored while real host conflicts remain visible',async()=>{
 const f=await fixture();try{
  const appDir=join(f.root,'mounted AppImage'),other=join(f.root,'other');await mkdir(appDir);await mkdir(other);
  await writeFile(join(appDir,'astrabridge'),'#!/bin/sh\nexit 0\n',{mode:0o755});
  let searchPath=[appDir,f.bin,other].join(delimiter);
  const cli=new CliRegistration(f.root,{platform:'linux',binDirectory:f.bin,applicationDirectory:appDir,searchPath:()=>searchPath});
  const empty=await cli.status(f.config);assert.equal(empty.shadowedBy,null);
  await cli.install(f.old,f.config,'installation','1','a');assert.equal((await cli.status(f.config)).pathReady,true);
  await cli.install(f.next,f.config,'installation','2','b');assert.equal((await cli.status(f.config)).application,f.next);
  await cli.uninstall(f.config);assert.equal((await cli.status(f.config)).enabled,false);
  await writeFile(join(other,'astrabridge'),'foreign',{mode:0o755});
  await assert.rejects(()=>cli.install(f.old,f.config,'installation','1','a'),/already in PATH/);
  searchPath=[appDir,f.bin].join(delimiter);await cli.install(f.old,f.config,'installation','1','a');
  searchPath=[appDir,other,f.bin].join(delimiter);assert.equal((await cli.status(f.config)).shadowedBy,join(other,'astrabridge'));
 }finally{await f.close();}
});
test('skill export uses the application when the optional CLI is missing, foreign or stale',async()=>{
 const f=await fixture();try{
  await mkdir(join(f.root,'skill'));await writeFile(join(f.root,'skill/SKILL.md'),'instructions');
  const core=new Core(f.root,f.config,undefined,{cli:f.cli,executable:f.next});
  core.configured=async()=>({name:'installation',installed:true,digest:'b'} as any);core.load=core.configured;
  core.release=async()=>({version:'2',digest:'b'} as any);
  const check=async(name:string)=>{
   const result=await core.exportSkill(join(f.root,name));
   assert.equal(result.command,undefined);assert.equal(result.executable,f.next);
   assert.deepEqual(JSON.parse(await readFile(join(f.root,name,'installation.json'),'utf8')),{executable:f.next,config:f.config});
  };
  await writeFile(f.cli.executable,'foreign',{mode:0o755});await check('foreign-command');
  assert.equal(await readFile(f.cli.executable,'utf8'),'foreign');await rm(f.cli.executable);
  await f.cli.install(f.old,f.config,'installation','1','a');await check('stale-command');
  await f.cli.install(f.old,join(f.root,'other-config'),'other','2','b');await check('other-installation');
  await f.cli.install(f.old,f.config,'installation','2','b');await rm(f.old);await check('missing-target');
  core.release=async()=>({version:'3',digest:'c'} as any);
  await assert.rejects(()=>core.exportSkill(join(f.root,'wrong-runtime')),/match this application/);
 }finally{await f.close();}
});
test('Windows registration keeps PATH ownership and a stable native shim',async()=>{
 const root=await mkdtemp(join(tmpdir(),'astra-cli-win-'));
 try{
  const resource=join(root,'resources'),bin=join(root,'bin');await mkdir(resource);await writeFile(join(resource,'cli-launcher.exe'),'native fixture');
  const app=join(root,'Application.exe'),config=join(root,'Configuration.json');await writeFile(app,'app');await writeFile(config,'{}');
  let added=0,removed=0;
  const cli=new CliRegistration(resource,{platform:'win32',binDirectory:bin,searchPath:()=>bin,windowsPath:{query:async()=>false,add:async()=>{added++;return added===1;},remove:async()=>{removed++;return true;}}});
  await cli.install(app,config,'installation','1','a');const exe=await readFile(cli.executable);
  assert.ok((await readFile(join(bin,'cli-target.ini'))).toString('utf16le').includes('Executable="'+app+'"'));
  await cli.refresh(app,config,'installation','2','b');assert.deepEqual(await readFile(cli.executable),exe);
  await cli.uninstall(config);assert.equal(removed,1);assert.equal(added,1);
  const existing=new CliRegistration(resource,{platform:'win32',binDirectory:bin,searchPath:()=>bin,windowsPath:{query:async()=>true,add:async()=>false,remove:async()=>{throw Error('Must retain pre-existing PATH entry');}}});
  await existing.install(app,config,'installation','1','a');await existing.uninstall(config);
 }finally{await rm(root,{recursive:true,force:true});}
});


test('setup reset removes its CLI registration without touching another installation',async()=>{
 const f=await fixture();try{
  await f.cli.install(f.old,f.config,'installation','1','a');
  const core=new Core(f.root,f.config,undefined,{cli:f.cli,executable:f.old});
  core.backend=()=>({inspect:async()=>({running:false})} as any);
  await core.resetSetup();assert.equal((await f.cli.status()).enabled,false);
  await writeFile(f.config,'{}');await f.cli.install(f.old,join(f.root,'another.json'),'other','1','a');
  await core.resetSetup();assert.equal((await f.cli.status()).enabled,true);
 }finally{await f.close();}
});
test('an older application cannot explicitly register against a mismatched runtime',async()=>{
 const f=await fixture();try{
  const core=new Core(f.root,f.config,undefined,{cli:f.cli,executable:f.old});
  core.configured=async()=>({name:'installation',installed:true,digest:'new'} as any);
  core.release=async()=>({version:'1',digest:'old'} as any);
  await assert.rejects(()=>core.installCli(),/matching application/);
  assert.equal((await f.cli.status()).enabled,false);
 }finally{await f.close();}
});

test('Windows self-uninstall disables the target and defers a locked executable',async()=>{
 const root=await mkdtemp(join(tmpdir(),'astra-cli-locked-'));
 try{
  const resources=join(root,'resources'),bin=join(root,'bin');await mkdir(resources);await writeFile(join(resources,'cli-launcher.exe'),'native');
  const app=join(root,'Application.exe'),config=join(root,'config.json');await writeFile(app,'app');await writeFile(config,'{}');
  let locked=true,deferred=false;
  const cli:CliRegistration=new CliRegistration(resources,{platform:'win32',binDirectory:bin,searchPath:()=>bin,
   windowsPath:{query:async()=>false,add:async()=>true,remove:async()=>true},
   removeLauncher:async path=>{if(locked)throw Object.assign(Error('in use'),{code:'EPERM'});await rm(path);},
   deferRemoval:async(path,hash)=>{assert.equal(path,cli.executable);assert.equal(hash.length,64);deferred=true;}});
  await cli.install(app,config,'installation','1','a');
  assert.deepEqual(await cli.uninstall(config),{removed:true,cleanupPending:true});assert.ok(deferred);
  const status=await cli.status(config);assert.equal(status.enabled,false);assert.equal(status.pathReady,false);assert.equal(status.removalPending,true);
  assert.ok((await readFile(join(bin,'cli-target.ini'))).toString('utf16le').includes('Schema=0'));
  assert.equal(await cli.refresh(app,config,'installation','2','b'),false,'An update must not revive a removal');
  locked=false;await cli.uninstall(config);await assert.rejects(()=>access(cli.executable));
 }finally{await rm(root,{recursive:true,force:true});}
});
