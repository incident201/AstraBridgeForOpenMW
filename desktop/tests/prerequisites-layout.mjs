/** Host-requirements UI; no game, downloads or container operations. */
import {chromium} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import assert from 'node:assert/strict';
const output=process.env.ASTRA_TEST_OUTPUT;if(!output)throw Error('Set ASTRA_TEST_OUTPUT');await mkdir(output,{recursive:true});
const browser=await chromium.launch();const page=await browser.newPage({viewport:{width:960,height:680}});const errors=[];
page.on('pageerror',e=>errors.push(String(e)));
await page.addInitScript(()=>{
 const checks=[
  {id:'podman',title:'Podman 5+',status:'error',detail:'podman was not found in PATH.',remedy:'Install podman.'},
  {id:'crun',title:'crun',status:'error',detail:'crun was not found in PATH.',remedy:'Install crun; AstraBridge selects it explicitly.'},
  {id:'network',title:'Rootless networking',status:'error',detail:'Neither pasta nor slirp4netns was found.',remedy:'Install passt, which provides pasta, the default for Podman 5+.'},
  {id:'nvidia',title:'NVIDIA Container Toolkit / CDI',status:'error',detail:'nvidia-ctk was not found. A working host driver alone does not expose NVIDIA to containers.',remedy:'Install nvidia-container-toolkit, then run nvidia-ctk cdi list. It must include nvidia.com/gpu=all.'},
  ...['Rootless user','newuidmap','newgidmap','Subordinate UID range','Subordinate GID range','User namespaces','GPU render devices','AMD kernel driver','NVIDIA driver'].map(title=>({id:title,title,status:'ok',detail:'Available.'}))];
 window.requirementFixture={calls:[],resolved:false};
 window.astra={subscribe:()=>()=>{},input:()=>{},invoke:async(op)=>{
  window.requirementFixture.calls.push(op);
  if(op==='status')return {installed:false,release:{version:'0.3.0'}};
  if(op==='prerequisites')return {available:window.requirementFixture.resolved,version:'',checks:window.requirementFixture.resolved?checks.map(c=>({...c,status:'ok',detail:'Available.',remedy:undefined})):checks};
  throw Error('Unexpected operation '+op);
 }};
});
try{
 await page.goto(process.env.ASTRA_TEST_URL??'http://127.0.0.1:19888');
 await page.getByRole('heading',{name:'System requirements',exact:true}).waitFor();
 assert.ok(await page.getByText('NVIDIA Container Toolkit / CDI',{exact:true}).isVisible());
 for(const [width,height] of [[960,680],[1280,720]]){
  await page.setViewportSize({width,height});
  const bounds=await page.evaluate(()=>({pageHeight:document.documentElement.scrollHeight,height:innerHeight,pageWidth:document.documentElement.scrollWidth,width:innerWidth,list:document.querySelector('.requirements-list').getBoundingClientRect().height}));
  assert.ok(bounds.pageHeight<=height+1&&bounds.pageWidth<=width+1);assert.ok(bounds.list>300);
  await page.screenshot({path:join(output,`requirements-${width}.png`)});
 }
 await page.evaluate(()=>window.requirementFixture.resolved=true);
 await page.getByRole('button',{name:'Check again',exact:true}).click();
 await page.getByText('Required host checks passed.',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Back to setup',exact:true}).click();
 await page.getByPlaceholder('Choose your existing Morrowind folder').waitFor();
 assert.deepEqual(errors,[]);
 const calls=await page.evaluate(()=>window.requirementFixture.calls);
 assert.equal(calls.filter(op=>op==='prerequisites').length,2);
 assert.ok(!calls.includes('install')&&!calls.includes('start'));
 await writeFile(join(output,'result.json'),JSON.stringify({passed:true,calls,browserErrors:errors},null,2));
 console.log('Requirements appear automatically, fit the viewport and refresh after installation.');
}finally{await browser.close();}
