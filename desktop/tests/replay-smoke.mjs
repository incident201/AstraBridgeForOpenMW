/** Explicit integration against a disposable game fixture: DVR cannot pause gameplay. */
import {_electron as electron} from '@playwright/test';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
process.chdir(fileURLToPath(new URL('..',import.meta.url)));
const configPath=process.env.ASTRA_CONFIG,output=process.env.ASTRA_TEST_OUTPUT,save=process.env.ASTRA_TEST_SAVE;
if(!configPath||!output||!save)throw Error('Set ASTRA_CONFIG, ASTRA_TEST_OUTPUT and ASTRA_TEST_SAVE');
await mkdir(output,{recursive:true});const cfg=JSON.parse(await readFile(configPath,'utf8'));let token,app,page,acting=true,actor;
const report={},errors=[];
async function api(path,data,method=data===undefined?'GET':'POST'){
 const response=await fetch(`http://127.0.0.1:${cfg.apiPort}${path}`,{method,signal:AbortSignal.timeout(120000),
  headers:{Authorization:'Bearer '+cfg.token,'Content-Type':'application/json',...(token?{'X-Astra-Session':token}:{})},
  ...(data===undefined?{}:{body:JSON.stringify(data)})});const value=await response.json();if(!value.ok)throw Error(JSON.stringify(value));return value.result;
}
const game=(op,args={})=>api('/v1/game/command',{op,args});
async function launch(){
 const instance=await electron.launch({executablePath:resolve('node_modules/electron/dist/electron'),args:[resolve('.'),'--ozone-platform=x11'],env:{...process.env,
 ASTRA_CONFIG:resolve(configPath),ASTRA_RESOURCES:resolve('resources'),ASTRA_DESKTOP_DATA:join(resolve(output),'userdata')}});
 await instance.evaluate(({dialog})=>{globalThis.closeDialogs=[];globalThis.closeChoice=0;dialog.showMessageBox=async(...args)=>{
  const options=args.at(-1);globalThis.closeDialogs.push(options);return {response:globalThis.closeChoice,checkboxChecked:false};};});
 return instance;
}
try{
 await api('/v1/runtime/engine/start',{});token=(await api('/v1/agent/connect',{name:'Replay fixture'})).session_token;
 const saves=(await game('saves')).saves.filter(s=>s.description===save);assert.equal(saves.length,1);await game('load',{ref:saves[0].ref});
 await api('/v1/runtime/recording/start',{});
 actor=(async()=>{for(let i=0;acting&&i<90;i++)await game('act',{yaw:i%2?20:-20,seconds:2});})();
 app=await launch();page=await app.firstWindow();page.on('pageerror',e=>errors.push(String(e)));
 page.on('console',message=>{if(message.type()==='error')console.log('Renderer:',message.text());});
 await page.getByRole('button',{name:'Open viewer',exact:true}).click({timeout:30000});
 await page.waitForFunction(()=>Number(document.querySelector('.timeline-range')?.max)>4,{},{timeout:60000});
 console.log('Recording fragments available');
 const seek=async value=>{await page.getByLabel('Recording timeline').evaluate((el,value)=>{el.value=String(value);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));},value);};
 await seek(1);
 await page.waitForFunction(()=>{const v=document.querySelector('video[aria-label="Recording replay"]');return v?.readyState>=2&&v.currentTime>.8&&!document.querySelector('.replay-loading');},{},{timeout:25000});
 report.replay=await page.getByLabel('Recording replay').evaluate(v=>({time:v.currentTime,paused:v.paused,width:v.videoWidth,height:v.videoHeight}));
 assert.ok(report.replay.paused);assert.equal(report.replay.width,1920);
 const before=await api('/v1/runtime/status');await page.waitForTimeout(1800);const after=await api('/v1/runtime/status');
 assert.ok(after.media_samples>before.media_samples&&after.recording.frames>before.recording.frames,'Replay paused gameplay or recording');
 assert.equal(after.owner.mode,'agent');
 const pausedTime=await page.getByLabel('Recording replay').evaluate(v=>v.currentTime);assert.ok(Math.abs(pausedTime-report.replay.time)<.02);
 report.background={samples:after.media_samples-before.media_samples,frames:after.recording.frames-before.recording.frames};
 await page.getByRole('button',{name:'Play playback',exact:true}).click();await page.waitForFunction(t=>document.querySelector('video[aria-label="Recording replay"]').currentTime>t+.4,pausedTime);
 await page.getByRole('button',{name:'Pause playback',exact:true}).click();
 await seek(.3);await page.waitForFunction(()=>{const v=document.querySelector('video[aria-label="Recording replay"]');return v?.readyState>=2&&v.currentTime<.5&&!document.querySelector('.replay-loading');});
 await page.screenshot({path:join(output,'replay.png')});
 const liveFrames=(await api('/v1/runtime/status')).viewer.frames;
 await page.getByRole('button',{name:'Return to live',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('video[aria-label="Live Morrowind game"]').classList.contains('concealed'));
 assert.ok((await api('/v1/runtime/status')).viewer.frames>=liveFrames,'Returning to live restarted the stream');
 acting=false;await actor;actor=null;
 report.recording=await api('/v1/runtime/recording/stop',{});assert.equal(report.recording.error,null);
 await seek(.6);await page.waitForFunction(()=>document.querySelector('video[aria-label="Recording replay"]')?.readyState>=2&&!document.querySelector('.replay-loading'),{},{timeout:20000});
 report.finalReplay=await page.getByLabel('Recording replay').evaluate(v=>({time:v.currentTime,width:v.videoWidth}));
 await page.getByRole('button',{name:'Return to live',exact:true}).click();
 await api('/v1/agent/disconnect',{});token=undefined;
 await page.getByRole('button',{name:'Take manual control',exact:true}).click();
 await page.getByRole('button',{name:'Release control',exact:true}).waitFor();
 await api('/v1/runtime/recording/start',{});
 await page.waitForTimeout(4500);
 await seek(.4);await page.waitForFunction(()=>document.querySelector('video[aria-label="Recording replay"]')?.readyState>=2&&!document.querySelector('.replay-loading'),{},{timeout:20000});
 const manualBefore=await api('/v1/runtime/status');await page.waitForTimeout(1500);const manualAfter=await api('/v1/runtime/status');
 assert.equal(manualAfter.owner.mode,'manual');assert.ok(manualAfter.world_active);
 assert.ok(manualAfter.media_samples>manualBefore.media_samples&&manualAfter.recording.frames>manualBefore.recording.frames,'Replaying paused manual gameplay');
 report.manualBackground={samples:manualAfter.media_samples-manualBefore.media_samples,frames:manualAfter.recording.frames-manualBefore.recording.frames};
 await page.getByRole('button',{name:'Return to live',exact:true}).click();
 await page.getByRole('button',{name:'Release control',exact:true}).click();
 await page.getByRole('button',{name:'Take manual control',exact:true}).waitFor();
 await api('/v1/runtime/recording/stop',{});
 token=(await api('/v1/agent/connect',{name:'Close fixture'})).session_token;
 await api('/v1/runtime/recording/start',{});await game('act',{yaw:10,seconds:2});
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].close());await page.waitForTimeout(300);
 assert.ok((await api('/v1/runtime/status')).recording.recording);
 assert.equal(await app.evaluate(()=>globalThis.closeDialogs.length),1);report.cancelKeptWindow=true;
 await app.evaluate(()=>globalThis.closeChoice=1);await app.close();app=null;
 const kept=await api('/v1/runtime/status');assert.ok(kept.running&&kept.recording.recording);assert.equal(kept.owner.mode,'agent');report.keepRunning=true;
 await game('act',{yaw:-10,seconds:1});
 app=await launch();page=await app.firstWindow();await page.getByRole('heading',{name:'Play',exact:true}).waitFor();
 await app.evaluate(()=>globalThis.closeChoice=2);await app.close();app=null;report.stopClosedWindow=true;
 assert.deepEqual(errors,[]);report.passed=true;console.log(JSON.stringify({passed:true,background:report.background,keepRunning:true,stopClosedWindow:true}));
}catch(error){report.error=String(error);if(page)await page.screenshot({path:join(output,'failure.png')}).catch(()=>{});throw error;}
finally{
 acting=false;if(actor)await actor.catch(()=>{});
 if(app){await app.evaluate(({dialog})=>dialog.showMessageBox=async()=>({response:1,checkboxChecked:false})).catch(()=>{});await app.close().catch(()=>{});}
 if(token){await api('/v1/runtime/recording/stop',{}).catch(()=>{});await api('/v1/agent/disconnect',{}).catch(()=>{});}
 await writeFile(join(output,'result.json'),JSON.stringify({...report,rendererErrors:errors},null,2)+'\n');
}
