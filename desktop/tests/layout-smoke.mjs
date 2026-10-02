/** Check viewport fitting in a real Electron renderer. No game actions are sent. */
import {_electron as electron} from '@playwright/test';
import {resolve,join} from 'node:path';
import {mkdir,writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
process.chdir(fileURLToPath(new URL('..',import.meta.url)));
const output=process.env.ASTRA_TEST_OUTPUT;
if(!process.env.ASTRA_CONFIG||!output)throw new Error('Set ASTRA_CONFIG and ASTRA_TEST_OUTPUT');
await mkdir(output,{recursive:true});const results=[];
let app;
async function fit(page,name){
 const layout=await page.evaluate(()=>{
  const main=document.querySelector('main');
  return {width:innerWidth,height:innerHeight,document:document.documentElement.scrollHeight,body:document.body.scrollHeight,
   main:[main.clientHeight,main.scrollHeight],
   controls:[...document.querySelectorAll('main>header,.viewer-controls,.bottom-actions,.card-footer')].map(e=>{const b=e.getBoundingClientRect();return {top:b.top,bottom:b.bottom};}),
   video:(()=>{const v=document.querySelector('.video-wrap video');if(!v)return null;const b=v.getBoundingClientRect();return {top:b.top,bottom:b.bottom,height:b.height,fit:getComputedStyle(v).objectFit};})(),
   icons:[...document.querySelectorAll('button > .icon,.metric-icon > .icon')].map(icon=>{const b=icon.getBoundingClientRect();const p=(icon.closest('.metric')??icon.parentElement).getBoundingClientRect();return Math.abs((b.top+b.bottom-p.top-p.bottom)/2);}),
   forms:[...document.querySelectorAll('.settings-fields,.setup-fields')].map(e=>[e.clientHeight,e.scrollHeight])};
 });
 results.push({name,...layout});
 assert.ok(layout.document<=layout.height+1,name+' document overflow');
 assert.ok(layout.main[1]<=layout.main[0]+1,name+' main overflow');
 for(const b of layout.controls)assert.ok(b.top>=0&&b.bottom<=layout.height,name+' control outside viewport');
 for(const offset of layout.icons)assert.ok(offset<=1,name+' icon not vertically centered: '+offset);
 for(const [height,scroll] of layout.forms)assert.ok(scroll<=height+1,name+' form needs vertical scrolling');
 if(layout.video){assert.equal(layout.video.fit,'contain');assert.ok(layout.video.height>=layout.height*.68&&layout.video.top>=0&&layout.video.bottom<=layout.height,'Game preview must retain most of the window height');}
 await page.screenshot({path:join(output,name+'.png')});
}
try{
 app=await electron.launch({executablePath:resolve('node_modules/electron/dist/electron'),args:[resolve('.'),'--ozone-platform=x11'],
  env:{...process.env,ASTRA_RESOURCES:resolve('resources'),ASTRA_DESKTOP_DATA:join(resolve(output),'userdata')}});
 const page=await app.firstWindow();await page.getByRole('button',{name:'Open viewer',exact:true}).click({timeout:30000});
 await page.waitForFunction(()=>document.querySelector('video')?.currentTime>1,{},{timeout:90000});
 for(const [width,height] of [[1920,1080],[1280,720],[960,680]]){
  await page.setViewportSize({width,height});await fit(page,`play-${width}x${height}`);
 }
 await page.setViewportSize({width:1920,height:1080});
 await page.getByRole('button',{name:'Fullscreen',exact:true}).click();
 await page.waitForFunction(()=>Boolean(document.querySelector('.viewer-panel.viewer-fullscreen')));
 await page.waitForFunction(()=>getComputedStyle(document.querySelector('.viewer-panel > .section-heading')).opacity==='0',{},{timeout:7000});
 const full=await page.locator('.video-wrap').evaluate(e=>{const b=e.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height,viewport:[innerWidth,innerHeight]};});
 assert.equal(full.x,0);assert.equal(full.y,0);assert.equal(full.width,full.viewport[0]);assert.equal(full.height,full.viewport[1]);
 await page.screenshot({path:join(output,'fullscreen.png')});
 results.push({name:'fullscreen',...full});
 await page.mouse.move(30,30);await page.getByRole('button',{name:'Exit fullscreen',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('.viewer-panel.viewer-fullscreen'));
 await page.getByRole('button',{name:'Fullscreen',exact:true}).click();await page.waitForFunction(()=>Boolean(document.querySelector('.viewer-panel.viewer-fullscreen')));
 await page.waitForFunction(()=>document.activeElement?.tagName==='VIDEO');
 await page.keyboard.press('Escape');await page.waitForTimeout(300);
 assert.ok(await page.locator('.viewer-panel').evaluate(e=>e.classList.contains('viewer-fullscreen')),'Escape must not exit the game viewer');
 await page.mouse.move(30,30);await page.getByRole('button',{name:'Exit fullscreen',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('.viewer-panel.viewer-fullscreen'));
 await page.setViewportSize({width:960,height:680});await fit(page,'play-after-fullscreen');
 await page.getByRole('navigation').getByRole('button',{name:'Settings',exact:true}).click();
 await page.getByRole('button',{name:'Save configuration',exact:true}).waitFor();
 for(const name of ['Game data','Gameplay','Graphics and recording']){
  await page.getByRole('button',{name,exact:true}).click();await fit(page,'settings-'+name.replaceAll(' ','-'));
 }
 for(const name of ['Atlas','Recordings','Profiles','Diagnostics','Setup']){
  await page.getByRole('navigation').getByRole('button',{name,exact:true}).click();
  await page.getByRole('heading',{name,level:1,exact:true}).waitFor();
  if(name==='Recordings'&&await page.locator('.node-row').count()){
    await page.locator('.node-row').first().click();
    await page.waitForFunction(()=>document.querySelector('video.playback')?.readyState>=1,{},{timeout:15000});
  }
  await fit(page,name.toLowerCase());
 }
 await app.evaluate(({dialog})=>{dialog.showMessageBox=async()=>({response:1,checkboxChecked:false});});await app.close();app=null;
 app=await electron.launch({executablePath:resolve('node_modules/electron/dist/electron'),args:[resolve('.'),'--ozone-platform=x11'],
  env:{...process.env,ASTRA_CONFIG:join(resolve(output),'not-installed.json'),ASTRA_RESOURCES:resolve('resources'),ASTRA_DESKTOP_DATA:join(resolve(output),'setup-userdata')}});
 const setup=await app.firstWindow();await setup.setViewportSize({width:960,height:680});
 await setup.getByRole('button',{name:'Open setup',exact:true}).click();await fit(setup,'setup-game');
 await setup.getByPlaceholder('Choose your existing Morrowind folder').fill('/example/game');
 await setup.getByRole('button',{name:'Next: Storage',exact:true}).click();await fit(setup,'setup-storage');
 console.log(JSON.stringify({passed:true,viewports:results.map(x=>({name:x.name,videoHeight:x.video?.height}))}));
}finally{if(app){await app.evaluate(({dialog})=>{dialog.showMessageBox=async()=>({response:1,checkboxChecked:false});});await app.close();}await writeFile(join(output,'layout.json'),JSON.stringify(results,null,2)+'\n');}
