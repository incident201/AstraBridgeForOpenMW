/** Run explicitly against a disposable installed game fixture and a real host display. */
import {_electron as electron} from '@playwright/test';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
process.chdir(fileURLToPath(new URL('..',import.meta.url)));

const configPath=process.env.ASTRA_CONFIG,output=process.env.ASTRA_TEST_OUTPUT,save=process.env.ASTRA_TEST_SAVE;
if(!configPath||!output||!save)throw new Error('Set ASTRA_CONFIG, ASTRA_TEST_OUTPUT and ASTRA_TEST_SAVE to a disposable test installation, result directory and save description');
await mkdir(output,{recursive:true});
const config=JSON.parse(await readFile(configPath,'utf8'));let agent;
async function api(path,data,method=data===undefined?'GET':'POST'){
  const response=await fetch(`http://127.0.0.1:${config.apiPort}${path}`,{method,signal:AbortSignal.timeout(120000),
    headers:{Authorization:'Bearer '+config.token,'Content-Type':'application/json',...(agent?{'X-Astra-Session':agent}:{})},
    ...(data===undefined?{}:{body:JSON.stringify(data)})});
  const value=await response.json();if(!response.ok||!value.ok)throw new Error(JSON.stringify(value));return value.result;
}
const game=(op,args={})=>api('/v1/game/command',{op,args});
const report={},errors=[];let app,page;
try{
  const initial=await api('/v1/runtime/status');assert.equal(initial.owner.mode,'idle','Fixture must have no active controller');
  await api('/v1/runtime/engine/start',{});
  agent=(await api('/v1/agent/connect',{name:'Desktop integration fixture'})).session_token;
  const saves=(await game('saves')).saves.filter(item=>item.description===save);assert.equal(saves.length,1);
  await game('load',{ref:saves[0].ref});await api('/v1/agent/disconnect',{});agent=undefined;
  app=await electron.launch({executablePath:resolve('node_modules/electron/dist/electron'),
    args:[resolve('.'),'--ozone-platform=x11'],env:{...process.env,
      ASTRA_CONFIG:resolve(configPath),ASTRA_RESOURCES:resolve('resources'),ASTRA_DESKTOP_DATA:join(resolve(output),'userdata')}});
  page=await app.firstWindow();page.on('pageerror',error=>errors.push(String(error)));
  await page.getByRole('button',{name:'Open viewer',exact:true}).click({timeout:30000});
  await page.waitForFunction(()=>{const v=document.querySelector('video');return v?.videoWidth===1280&&v.currentTime>1;},{},{timeout:90000});
  report.viewer720=await page.locator('video[aria-label="Live Morrowind game"]').evaluate(v=>({width:v.videoWidth,height:v.videoHeight,time:v.currentTime,tracks:v.srcObject.getTracks().map(t=>({kind:t.kind,state:t.readyState,muted:t.muted}))}));
  await page.screenshot({path:join(output,'play.png')});
  await page.getByLabel('Viewer options',{exact:true}).click();
  await page.getByLabel('Viewer quality').selectOption('1080p60');
  await page.waitForFunction(()=>document.querySelector('video')?.videoWidth===1920,{},{timeout:90000});
  report.viewer1080=await page.locator('video[aria-label="Live Morrowind game"]').evaluate(v=>({width:v.videoWidth,height:v.videoHeight}));
  await page.getByRole('button',{name:'Fullscreen',exact:true}).click();
  await page.mouse.move(10,10);await page.getByRole('button',{name:'Take manual control',exact:true}).click();
  await page.getByRole('button',{name:'Release control',exact:true}).waitFor();
  await page.locator('video[aria-label="Live Morrowind game"]').focus();await page.keyboard.press('j');
  await page.waitForTimeout(400);
  await page.mouse.move(10,10);await page.getByRole('button',{name:'Release control',exact:true}).click();
  agent=(await api('/v1/agent/connect',{name:'Ownership fixture'})).session_token;
  const journal=await game('observe');report.manualJournal=journal.ui_mode??journal.observation?.ui_mode;
  assert.equal(report.manualJournal,'Journal','Manual key must reach the game');
  await api('/v1/agent/disconnect',{});agent=undefined;
  await page.mouse.move(10,10);await page.getByRole('button',{name:'Take manual control',exact:true}).click();
  await page.getByRole('button',{name:'Release control',exact:true}).waitFor();
  await page.locator('video[aria-label="Live Morrowind game"]').focus();await page.keyboard.press('Escape');await page.waitForTimeout(400);
  assert.ok(await page.locator('.viewer-panel').evaluate(e=>e.classList.contains('viewer-fullscreen')));
  report.escapePreservesFullscreen=true;
  await page.keyboard.press('Backquote');await page.waitForTimeout(200);
  await page.mouse.move(10,10);await page.getByRole('button',{name:'Release control',exact:true}).click();
  agent=(await api('/v1/agent/connect',{name:'Console policy fixture'})).session_token;
  const observation=await game('observe');report.afterConsoleKey=observation.ui_mode??observation.observation?.ui_mode;
  assert.equal(report.afterConsoleKey,'Gameplay');
  await page.getByRole('button',{name:'Agent owns input',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Agent owns input',exact:true}).isDisabled(),true);
  await page.mouse.move(10,10);await page.getByRole('button',{name:'Exit fullscreen',exact:true}).click();
  assert.equal((await api('/v1/runtime/status')).owner.mode,'agent');
  await api('/v1/agent/disconnect',{});agent=undefined;
  for(const name of ['Atlas','Recordings','Settings','Diagnostics','Setup']){
    await page.getByRole('navigation').getByRole('button',{name,exact:true}).click();
    await page.getByRole('heading',{level:1,name,exact:true}).waitFor();
    if(name==='Settings'){
      await page.getByRole('button',{name:'Graphics and recording',exact:true}).click();
      await page.getByLabel('Encoding GPU',{exact:true}).waitFor();
      report.gpuOptions=await page.getByLabel('Encoding GPU',{exact:true}).locator('option').allTextContents();
    }
    await page.screenshot({path:join(output,name.toLowerCase()+'.png')});
  }
  await app.evaluate(({dialog})=>{dialog.showMessageBox=async()=>({response:1,checkboxChecked:false});});await app.close();app=null;report.afterGuiClose=await api('/v1/runtime/status');assert.ok(report.afterGuiClose.running);
  assert.deepEqual(errors,[]);report.passed=true;
}catch(error){report.error=String(error);if(page)await page.screenshot({path:join(output,'failure.png')}).catch(()=>{});throw error;}
finally{
  if(app){await app.evaluate(({dialog})=>{dialog.showMessageBox=async()=>({response:1,checkboxChecked:false});});await app.close();}if(agent)await api('/v1/agent/disconnect',{}).catch(()=>{});
  await api('/v1/runtime/live',undefined,'DELETE').catch(()=>{});
  await writeFile(join(output,'result.json'),JSON.stringify({...report,rendererErrors:errors},null,2)+'\n');
}
console.log(JSON.stringify({passed:true,viewer720:report.viewer720,viewer1080:report.viewer1080,gpuOptions:report.gpuOptions}));
