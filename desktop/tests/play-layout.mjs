/** Offline renderer checks: disposable API/media fixtures, no game or host actions. */
import {chromium} from '@playwright/test';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import assert from 'node:assert/strict';
const output=process.env.ASTRA_TEST_OUTPUT;
if(!output)throw Error('Set ASTRA_TEST_OUTPUT to a directory outside the source tree');
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});const results=[],errors=[];
const page=await browser.newPage();page.on('pageerror',e=>errors.push(String(e)));
if(process.env.ASTRA_TEST_FRAME)await page.route('**/fixture-frame.png',async route=>route.fulfill({contentType:'image/png',body:await readFile(process.env.ASTRA_TEST_FRAME)}));
await page.addInitScript(({hasFrame})=>{
 const handlers=[];let recording=false;
 const runtime={running:true,owner:{mode:'agent',name:'Gameplay agent'},profile:{id:'default',name:'Vvardenfell',active:true},active_action:{operation:'approach',phase:'Moving to target'},graphics:{hardware_accelerated:true,renderer:'NVIDIA GeForce RTX 3060 Laptop GPU / PCIe / SSE2'},game_fps:60,capture_fps:60,recording:null,viewer:{running:true}};
 const state={installed:true,release:{version:'0.3.0-dev'},backend:'podman',container:{running:true,exists:true},runtime};
 const emit=()=>handlers.forEach(fn=>fn({type:'status',data:structuredClone(runtime)}));
 window.fixture={state,runtime,calls:[],emit,set:(patch)=>{Object.assign(runtime,patch);emit();}};
 window.astra={subscribe:fn=>{handlers.push(fn);return()=>{};},input:message=>{
  window.fixture.calls.push(message);if(message.type==='manual.acquire')runtime.owner={mode:'manual'};
  if(message.type==='manual.release')runtime.owner={mode:'idle'};emit();
 },invoke:async(op,args)=>{
  window.fixture.calls.push({op,args});
  if(op==='status')return structuredClone(state);
  if(op==='replay-info')return window.fixture.replay??{id:null,ready:false,active:recording,duration:0};
  if(op==='viewer-fullscreen')return {enabled:args.enabled};
  if(op==='record'){if(window.fixture.failRecord)throw Error('Recording could not start. Check the output folder permissions.');recording=args.action==='start';runtime.recording=recording?{recording:true,duration:125,encoder:'h264_nvenc'}:null;emit();}
  if(op==='agent-end'){runtime.owner={mode:'idle'};emit();}
  if(op==='start'){runtime.running=true;state.container.running=true;emit();}
  if(op==='stop'){runtime.running=false;state.container.running=false;emit();}
  if(op==='whep')return {body:'fixture',location:'/fixture-peer'};
  return {};
 }};
 window.RTCPeerConnection=class {
  iceGatheringState='complete';localDescription={sdp:'fixture'};ontrack=null;timer=null;stream=null;
  addTransceiver(){} async createOffer(){return {sdp:'fixture',type:'offer'};}async setLocalDescription(){}
  async setRemoteDescription(){
   const canvas=document.createElement('canvas');canvas.width=1920;canvas.height=1080;const ctx=canvas.getContext('2d');
   let img=null;if(hasFrame){img=new Image();img.src='/fixture-frame.png';await img.decode();}
   const draw=()=>{if(img)ctx.drawImage(img,0,0);else {ctx.fillStyle='#182927';ctx.fillRect(0,0,1920,1080);ctx.fillStyle='#c5cfb5';ctx.font='32px sans-serif';ctx.fillText('Morrowind · preview fixture',60,90);} };
   draw();this.timer=setInterval(draw,100);this.stream=canvas.captureStream(10);this.ontrack?.({track:this.stream.getVideoTracks()[0]});
  }
  close(){clearInterval(this.timer);this.stream?.getTracks().forEach(t=>t.stop());}
 };
},{hasFrame:Boolean(process.env.ASTRA_TEST_FRAME)});
async function shot(name){
 const layout=await page.evaluate(()=>{
  const b=document.querySelector('.video-wrap').getBoundingClientRect();
  return {width:innerWidth,height:innerHeight,video:{x:b.x,y:b.y,width:b.width,height:b.height},
   imageHeight:Math.min(b.height,b.width*9/16),scroll:[document.documentElement.scrollWidth,document.documentElement.scrollHeight],
   mainOverflow:document.querySelector('main').scrollHeight-document.querySelector('main').clientHeight,
   notice:!!document.querySelector('main > .banner'),
   menus:[...document.querySelectorAll('details.dropdown[open] .menu-popover')].map(e=>{const b=e.getBoundingClientRect();return {x:b.x,y:b.y,right:b.right,bottom:b.bottom,hit:e.contains(document.elementFromPoint(b.x+b.width/2,b.y+b.height/2))};}),
   iconOffsets:[...document.querySelectorAll('button > .icon')].filter(e=>e.getClientRects().length).map(e=>{const a=e.getBoundingClientRect(),p=e.parentElement.getBoundingClientRect();return Math.abs((a.top+a.bottom-p.top-p.bottom)/2);})};
 });
 results.push({name,...layout});await page.screenshot({path:join(output,name+'.png')});
 assert.ok(layout.scroll[0]<=layout.width&&layout.scroll[1]<=layout.height,name+' page overflow');
 assert.ok(layout.mainOverflow<=1,name+' main overflow');
 assert.ok(layout.iconOffsets.every(x=>x<1),name+' uncentered icon');
 for(const m of layout.menus)assert.ok(m.x>=0&&m.y>=0&&m.right<=layout.width&&m.bottom<=layout.height&&m.hit,name+' clipped/covered menu');
 // A visible warning may consume one bounded row; ordinary play must keep more space.
 if(!process.argv.includes('--baseline'))assert.ok(layout.video.height>=layout.height*(layout.notice ? .60 : .68),name+' game viewport is too short');
 return layout;
}
try{
 await page.goto(process.env.ASTRA_UI_URL??'http://127.0.0.1:4178');
 await page.getByRole('button',{name:'Open viewer',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('video')?.currentTime>0);
 for(const [width,height] of [[1920,1080],[1440,900],[1320,900],[1280,720],[960,680]]){
  await page.setViewportSize({width,height});await shot(`agent-${width}x${height}`);
 }
 await page.evaluate(()=>window.fixture.set({owner:{mode:'idle'},active_action:null}));await shot('idle-960');
 await page.getByRole('button',{name:'Take manual control',exact:true}).click();await shot('manual-960');
 await page.getByRole('button',{name:'Release control',exact:true}).click();
 await page.getByRole('button',{name:'Pause playback',exact:true}).click();await shot('paused-960');
 await page.getByRole('button',{name:'Return to live',exact:true}).click();
 await page.getByRole('button',{name:'Start recording',exact:true}).click();
 await page.evaluate(()=>window.fixture.replay={id:'fixture-clip',ready:true,active:true,duration:125});
 await page.waitForFunction(()=>Number(document.querySelector('.timeline-range').max)===125);
 await shot('recording-960');
 await page.getByLabel('Session options',{exact:true}).click();await shot('session-menu-960');
 await page.keyboard.press('Escape');assert.equal(await page.locator('.session-menu[open]').count(),0);
 await page.getByLabel('Viewer options',{exact:true}).click();await shot('viewer-options-960');
 await page.getByLabel('Viewer quality').selectOption('1080p60');
 assert.equal(await page.locator('.viewer-options[open]').count(),0);
 await page.getByLabel('Viewer help',{exact:true}).click();await shot('help-960');
 await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'Fullscreen',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.viewer-panel')?.classList.contains('viewer-fullscreen'));
 await page.keyboard.press('Escape');assert.ok(await page.locator('.viewer-fullscreen').count(),'Escape exited fullscreen');
 await page.mouse.move(30,30);await shot('fullscreen-960');
 await page.getByRole('button',{name:'Take manual control',exact:true}).click();
 await page.getByLabel('Live Morrowind game',{exact:true}).focus();await page.keyboard.press('Escape');
 assert.ok(await page.locator('.viewer-fullscreen').count(),'Manual Escape exited fullscreen');
 assert.ok(await page.evaluate(()=>window.fixture.calls.some(x=>x.type==='input'&&x.event?.code==='Escape'&&x.event.down===true)),'Escape did not reach manual game input');
 await page.mouse.move(30,30);await page.getByRole('button',{name:'Release control',exact:true}).click();
 await page.getByRole('button',{name:'Stop recording',exact:true}).click();
 await page.evaluate(()=>window.fixture.failRecord=true);
 await page.getByRole('button',{name:'Start recording',exact:true}).click();
 await page.getByRole('alert').waitFor();await shot('fullscreen-recording-error');
 assert.ok(await page.getByRole('alert').evaluate(e=>e.contains(document.elementFromPoint(e.getBoundingClientRect().x+20,e.getBoundingClientRect().y+15))),'Fullscreen error covered');
 await page.getByRole('button',{name:'Dismiss error'}).click();
 await page.getByRole('button',{name:'Exit fullscreen',exact:true}).click();
 await page.getByLabel('Viewer options',{exact:true}).click();await page.getByRole('button',{name:'Disconnect viewer',exact:true}).click();
 await shot('disconnected-960');assert.equal(await page.locator('.live-button.active').count(),0);
 await page.evaluate(()=>window.fixture.set({running:false}));await shot('stopped-960');
 await page.evaluate(()=>window.fixture.set({running:true,owner:{mode:'agent',name:'A long named gameplay agent'},profile:{id:'default',name:'A very long profile name for an independent playthrough of Morrowind'},active_action:{operation:'follow_a_distant_moving_target',phase:'Moving'}}));
 await page.getByRole('button',{name:'Open viewer',exact:true}).click();await shot('long-labels-960');
 await page.evaluate(()=>window.fixture.state.updateRequired=true);
 await page.waitForFunction(()=>document.querySelector('.banner-action'));await shot('update-notice-960');
 assert.deepEqual(errors,[]);console.log(JSON.stringify(results.map(({name,video,imageHeight})=>({name,videoHeight:video.height,imageHeight})),null,2));
}finally{await writeFile(join(output,'layout.json'),JSON.stringify({results,errors},null,2));await browser.close();}
