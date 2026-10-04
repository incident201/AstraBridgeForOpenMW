import {chromium} from '@playwright/test';
import {mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';
const output=process.env.ASTRA_TEST_OUTPUT;if(!output)throw Error('Set ASTRA_TEST_OUTPUT');await mkdir(output,{recursive:true});
const browser=await chromium.launch();const page=await browser.newPage();
await page.addInitScript(()=>{
 let cli={enabled:false,command:'astrabridge',matches:false};
 window.fixture={calls:[]};
 window.astra={subscribe:()=>()=>{},input:()=>{},invoke:async op=>{
  window.fixture.calls.push(op);
  if(op==='status')return {installed:true,configured:true,currentVersion:'0.3.0',currentDigest:'release',release:{version:'0.3.0'},container:{exists:true,running:false},runtime:{running:false,profile:{name:'Default'}},sourceGame:'/home/player/Games/Morrowind',storageDirectory:'/home/player/Games/AstraBridge',recordingsDirectory:'/home/player/Videos/AstraBridge'};
  if(op==='cli-status')return cli;
  if(op==='cli-install'){cli={enabled:true,command:'astrabridge',matches:true,pathReady:false,targetAvailable:true,digest:'release',executable:'/home/player/.local/bin/astrabridge',guidance:'Add /home/player/.local/bin to PATH once, then restart the terminal or agent client.'};return cli;}
  if(op==='cli-uninstall'){cli={enabled:false,matches:false};return {removed:true};}
  if(op==='prerequisites')return {available:true};return {};
 }};
});
try{
 await page.goto(process.env.ASTRA_UI_URL??'http://127.0.0.1:4178');
 await page.getByRole('navigation').getByRole('button',{name:'Setup',exact:true}).click();
 await page.getByRole('button',{name:'Storage and skill',exact:true}).click();
 await page.getByRole('button',{name:'Enable CLI command',exact:true}).click();
 await page.getByText('Add /home/player/.local/bin to PATH once, then restart the terminal or agent client.',{exact:true}).waitFor();
 for(const [width,height] of [[960,680],[1280,720]]){
  await page.setViewportSize({width,height});
  await page.getByRole('button',{name:'Repair CLI command'}).scrollIntoViewIfNeeded();
  const rect=await page.getByLabel('CLI command setup').boundingBox();assert.ok(rect.height>0&&rect.y>=0&&rect.y+rect.height<=height);
  assert.ok(await page.locator('main').evaluate(e=>e.scrollHeight<=e.clientHeight+1));
  await page.screenshot({path:output+`/cli-${width}.png`});
 }
 await page.getByRole('button',{name:'Remove CLI command',exact:true}).click();
 await page.getByRole('button',{name:'Enable CLI command',exact:true}).waitFor();
 assert.ok(await page.evaluate(()=>window.fixture.calls.includes('cli-install')&&window.fixture.calls.includes('cli-uninstall')));
 console.log('CLI registration, PATH guidance and removal are reachable in Setup at both viewport sizes.');
}finally{await browser.close();}
