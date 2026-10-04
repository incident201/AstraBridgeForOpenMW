import {chromium} from '@playwright/test';
import {mkdir} from 'node:fs/promises';
import {join} from 'node:path';
import assert from 'node:assert/strict';
const output=process.env.ASTRA_TEST_OUTPUT;if(!output)throw Error('Set ASTRA_TEST_OUTPUT');await mkdir(output,{recursive:true});
const browser=await chromium.launch();const page=await browser.newPage({viewport:{width:960,height:680}});
await page.addInitScript(()=>{
 const runtime={running:false,starting:false,profile:{id:'default',name:'Default'},owner:{mode:'idle'}};
 const state={installed:true,configured:true,storageMissing:true,updatePending:true,container:{exists:false,running:false},runtime,release:{version:'test'},sourceGame:'/chosen/game',storageDirectory:'/chosen/storage',recordingsDirectory:'/chosen/videos'};
 let handlers=[],rejectStart;
 window.fixture={state,runtime,calls:[],emit:()=>handlers.forEach(fn=>fn({type:'status',data:structuredClone(runtime)}))};
 window.astra={subscribe:fn=>{handlers.push(fn);return()=>{};},input:()=>{},invoke:async(op)=>{
  window.fixture.calls.push(op);
  if(op==='status')return structuredClone(state);
  if(op==='prerequisites')return {available:true};
  if(op==='reset-setup'){state.installed=false;state.configured=false;state.storageMissing=false;state.updatePending=false;return {reset:true};}
  if(op==='start'){runtime.starting=true;state.container.running=true;window.fixture.emit();return new Promise((_resolve,reject)=>rejectStart=reject);}
  if(op==='stop'){runtime.starting=false;runtime.running=false;state.container.running=false;window.fixture.emit();rejectStart?.(Error('Game startup was cancelled.'));return {};}
  return {};
 }};
});
try{
 await page.goto(process.env.ASTRA_UI_URL??'http://127.0.0.1:4178');
 await page.getByRole('heading',{name:'Managed storage is missing',exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:'Recover interrupted update',exact:true}).count(),0);
 const fit=await page.locator('main').evaluate(e=>e.scrollHeight<=e.clientHeight+1);assert.ok(fit);
 await page.screenshot({path:join(output,'missing-storage.png')});
 await page.getByRole('button',{name:'Reset setup',exact:true}).click();
 await page.getByPlaceholder('Choose your existing Morrowind folder').waitFor();
 assert.equal(await page.getByPlaceholder('Choose your existing Morrowind folder').inputValue(),'/chosen/game');
 await page.getByRole('button',{name:'Next: Storage',exact:true}).click();
 assert.equal(await page.getByPlaceholder('Choose a storage location').inputValue(),'/chosen/storage');
 await page.evaluate(()=>{Object.assign(window.fixture.state,{installed:true,configured:true,storageMissing:false,updatePending:false,container:{exists:true,running:false}});});
 await page.getByRole('navigation').getByRole('button',{name:'Play',exact:true}).click();
 await page.getByRole('button',{name:'Start game',exact:true}).click();
 await page.getByRole('heading',{name:'Starting Morrowind…',exact:true}).waitFor();
 await page.getByLabel('Session options',{exact:true}).click();
 assert.ok(await page.getByRole('button',{name:'Stop runtime',exact:true}).isEnabled());
 await page.screenshot({path:join(output,'cancellable-startup.png')});
 await page.getByRole('button',{name:'Stop runtime',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.game-state').textContent.includes('Game stopped'));
 assert.ok(!(await page.locator('.game-state').textContent()).includes('running'));
 console.log('Missing storage returns to editable setup; loading has an enabled Stop action.');
}finally{await browser.close();}
