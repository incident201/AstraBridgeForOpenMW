/** Disposable rootless store only. Never use a real installation directory. */
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,access,rm} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
const output=process.env.ASTRA_TEST_OUTPUT;if(!output)throw Error('Set ASTRA_TEST_OUTPUT outside the source tree');
await mkdir(output,{recursive:true});const directory=await mkdtemp(join(resolve(output),'uninstall-'));
// This test is run with tsx, importing the same host backend used by Desktop.
const {Core}=await import('../main/core.ts');
const storage=join(directory,'managed'),configFile=join(directory,'installation.json'),recordings=join(directory,'recordings'),game=join(directory,'game');
await mkdir(recordings);await mkdir(game);await writeFile(join(recordings,'keep.mp4'),'video');await writeFile(join(game,'keep.esm'),'game');
const config={installed:true,name:'astrabridge-uninstall-smoke',backend:'podman',storageDirectory:storage,sourceGame:game,gameDirectory:game,gameMode:'mount',recordingsDirectory:recordings,stateVolume:'astrabridge-uninstall-state',gameVolume:'astrabridge-uninstall-game',image:'localhost/astrabridge-missing@sha256:'+'a'.repeat(64),digest:'sha256:'+'a'.repeat(64)};
await writeFile(configFile,JSON.stringify(config));await writeFile(join(directory,'release.json'),'{}');
const core=new Core(directory,configFile),backend=core.backend(config);
await backend.createVolume(config.stateVolume);
const args=['--root',join(storage,'containers'),'--runroot',join(storage,'run/podman'),'--runtime','crun'];
const volume=execFileSync('podman',[...args,'volume','inspect',config.stateVolume,'--format','{{.Mountpoint}}'],{encoding:'utf8'}).trim();
execFileSync('podman',[...args,'unshare','python3','-c',`import os,pathlib;p=pathlib.Path(${JSON.stringify(volume)})/'mapped-owner';p.mkdir();(p/'data').write_text('managed');os.chown(p/'data',1001,1001);os.chown(p,1001,1001);p.chmod(0o700)`]);
let denied=false;try{await readFile(join(volume,'mapped-owner/data'));}catch(e){denied=e.code==='EACCES';}
assert.ok(denied,'Fixture must reproduce a mapped UID directory inaccessible to the host user');
await core.uninstall();assert.equal(await core.load(),null);await assert.rejects(()=>access(join(storage,'containers')));
assert.equal(await readFile(join(game,'keep.esm'),'utf8'),'game');assert.equal(await readFile(join(recordings,'keep.mp4'),'utf8'),'video');
// Reproduce external rm -rf after container removal: configuration remains elsewhere.
await writeFile(configFile,JSON.stringify(config));await rm(storage,{recursive:true,force:true});
assert.equal((await core.status()).storageMissing,true);
await assert.rejects(()=>core.update(),/Managed storage is missing|requirements/);
await core.resetSetup();assert.equal(await core.load(),null);
console.log(JSON.stringify({rootlessUninstall:true,mappedUIDFilesRemoved:true,externalFilesKept:true,deletedStoreReset:true,directory}));
