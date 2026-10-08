// Exercise the public AppImage entry point, including AppRun's environment.
// Run on a disposable CI user or with ~/.local/bin privately bind-mounted.
import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdtemp,readFile,writeFile,lstat,rm} from 'node:fs/promises';
import {homedir,tmpdir} from 'node:os';
import {join,resolve} from 'node:path';

const exec=promisify(execFile),application=resolve(process.argv[2]);
const bin=join(homedir(),'.local/bin'),launcher=join(bin,'astrabridge');
await assert.rejects(()=>lstat(launcher),{code:'ENOENT'},'Use a disposable CLI directory; do not replace an existing command');
const root=await mkdtemp(join(tmpdir(),'astra-packaged-cli-')),config=join(root,'installation.json');
const env={...process.env,PATH:bin+':'+process.env.PATH};
delete env.DISPLAY;delete env.WAYLAND_DISPLAY;
async function call(executable,args){
 const {stdout}=await exec(executable,args,{env,maxBuffer:4*1024**2});
 const data=JSON.parse(stdout);assert.equal(data.ok,true,stdout);return data.result;
}
const app=(...args)=>call(application,['--config',config,...args]);
try{
 const release=await app('version');
 const tools=await app('agent','tools','--json');
 assert.equal(tools.schema_version,1);assert.equal(tools.release.digest,release.digest);
 assert.ok(tools.tools.some(tool=>tool.name==='astra_observe'&&tool.input_schema.type==='object'));
 await writeFile(config,JSON.stringify({name:'packaged-cli-test',installed:true,digest:release.digest}));
 assert.equal((await app('cli','status')).shadowedBy,null,'AppRun must not report its own command as a conflict');
 await app('skill','export',join(root,'without-command'));
 assert.deepEqual(JSON.parse(await readFile(join(root,'without-command/installation.json'),'utf8')),{executable:application,config});
 await app('skill','export',join(root,'native-tools'),'--interface','tools');
 assert.deepEqual(JSON.parse(await readFile(join(root,'native-tools/installation.json'),'utf8')),{executable:application,config,interface:'tools'});
 const nativeSkill=await readFile(join(root,'native-tools/SKILL.md'),'utf8');
 assert.ok(nativeSkill.includes('read_skill_reference'));assert.ok(!nativeSkill.includes('astrabridge game'));
 const installed=await app('cli','install');
 assert.equal(installed.enabled,true);assert.equal(installed.pathReady,true);assert.equal(installed.shadowedBy,null);
 assert.equal((await app('cli','status')).pathReady,true);
 assert.equal((await call(launcher,['version'])).digest,release.digest);
 await app('cli','install'); // Repair from the AppImage, with its injected PATH.
 await app('skill','export',join(root,'with-command'));
 assert.deepEqual(JSON.parse(await readFile(join(root,'with-command/installation.json'),'utf8')),{command:'astrabridge',executable:launcher,config});
 assert.equal((await call(launcher,['cli','uninstall'])).removed,true);
 await assert.rejects(()=>lstat(launcher),{code:'ENOENT'});
 await app('skill','export',join(root,'after-removal'));
 assert.equal((await app('cli','install')).pathReady,true);
 assert.equal((await app('cli','uninstall')).removed,true);
 console.log('Public AppImage: CLI install, repair, short command, skill export, self-uninstall and reinstall passed. Export also passed before installation and after removal.');
}finally{
 await app('cli','uninstall').catch(error=>{console.error('CLI cleanup failed:',error.message);process.exitCode=1;});
 await rm(root,{recursive:true,force:true});
}
