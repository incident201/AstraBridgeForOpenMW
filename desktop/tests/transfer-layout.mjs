import {chromium} from '@playwright/test';
import {mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';
const out=process.env.ASTRA_TEST_OUTPUT;if(!out)throw Error('Set ASTRA_TEST_OUTPUT');await mkdir(out,{recursive:true});
const browser=await chromium.launch();const page=await browser.newPage();
await page.addInitScript(()=>{
 const subscribers=[];
 const state={installed:true,configured:true,updateRequired:true,currentVersion:'0.3.0-rc9',currentDigest:'sha256:example',release:{version:'next'},container:{running:false,exists:true},runtime:{running:false,profile:{id:'default',name:'Default'}}};
 window.fixture={emit:(type,data)=>subscribers.forEach(fn=>fn({type,data}))};
 window.astra={subscribe:fn=>{subscribers.push(fn);return()=>{};},input:()=>{},invoke:async op=>{
  if(op==='status')return state;
  if(op==='prerequisites')return {available:true};
  if(op==='update')return new Promise(()=>{});
  return {};
 }};
});
try{
 await page.goto(process.env.ASTRA_UI_URL??'http://127.0.0.1:4178');
 await page.getByRole('navigation').getByRole('button',{name:'Setup',exact:true}).click();
 await page.getByRole('button',{name:'Update runtime',exact:true}).click();
 const sample={type:'transfer',phase:'downloading',image:'runtime',received:64*1024**2,total:100*1024**2,reused:270*1024**2,speed:2*1024**2,elapsed:35,idle:0,layers:10,completed:7};
 await page.evaluate(p=>window.fixture.emit('transfer',p),sample);
 for(const [width,height] of [[960,680],[1280,720]]){
  await page.setViewportSize({width,height});
  const panel=page.getByLabel('Runtime download progress',{exact:true});await panel.waitFor();
  assert.ok((await panel.textContent()).includes('64%'));
  assert.ok((await panel.textContent()).includes('270.0 MiB reused'));
  const box=await panel.boundingBox();assert.ok(box.y>=0&&box.y+box.height<=height);
  await page.screenshot({path:out+`/download-${width}.png`});
 }
 await page.evaluate(p=>window.fixture.emit('transfer',{...p,total:null,idle:40}),sample);
 assert.equal(await page.getByLabel('Image download',{exact:true}).getAttribute('value'),null);
 await page.screenshot({path:out+'/waiting.png'});
 await page.evaluate(p=>{window.fixture.emit('transfer',{...p,phase:'complete'});window.fixture.emit('stage',{message:'Backing up saves, profile, Atlas and session data…'});},sample);
 await page.locator('.setup-stage').waitFor();
 assert.ok((await page.locator('.setup-stage').textContent()).includes('Backing up saves'));
 assert.ok(await page.locator('.setup-stage').evaluate(e=>parseFloat(getComputedStyle(e).fontSize)>0));
 await page.screenshot({path:out+'/backup.png'});
 console.log('Download counters, indeterminate wait and post-download stages fit the setup viewport.');
}finally{await browser.close();}
