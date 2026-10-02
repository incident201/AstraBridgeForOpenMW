/** Visual fixtures for management screens. Never talks to a game or container. */
import {chromium} from '@playwright/test';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import assert from 'node:assert/strict';
const output=process.env.ASTRA_TEST_OUTPUT;if(!output)throw Error('Set ASTRA_TEST_OUTPUT');await mkdir(output,{recursive:true});
const browser=await chromium.launch();const page=await browser.newPage();const results=[],errors=[];
page.on('pageerror',e=>errors.push(String(e)));
if(process.env.ASTRA_TEST_FRAME)await page.route('**/fixture-frame.png',async r=>r.fulfill({contentType:'image/png',body:await readFile(process.env.ASTRA_TEST_FRAME)}));
const svg=process.env.ASTRA_TEST_ATLAS?await readFile(process.env.ASTRA_TEST_ATLAS,'utf8'):'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#101923"/><path d="M100 460 280 360 400 300 580 140" fill="none" stroke="#5bd5ea" stroke-width="4"/><g fill="#ffc777" font-family="sans-serif" font-size="20"><text x="100" y="445">A1</text><text x="400" y="285">A2</text><text x="580" y="125">A3</text></g></svg>';
const atlasData=process.env.ASTRA_TEST_ATLAS_DATA?JSON.parse(await readFile(process.env.ASTRA_TEST_ATLAS_DATA,'utf8')):null;
await page.addInitScript(({svg,hasFrame,atlasData})=>{
 const handlers=[];let counter=30;
 const profiles=Array.from({length:14},(_,i)=>({id:'profile-'+i,name:i===0?'Vvardenfell':i===1?'A second journey through the coast of Vvardenfell with extensive notes':'Playthrough '+(i+1),active:i===0,created:1790000000-i*86400}));
 const runtime={running:false,profile:profiles[0],owner:{mode:'idle'},capture_fps:59.9,viewer:{quality:'1080p60',encoder:{encoder:'h264_vaapi'},audio_discontinuities:0}};
 const state={installed:true,runtime,backend:'podman',release:{version:'0.3.0-dev'},currentVersion:'0.3.0-dev',currentDigest:'sha256:'+'a1'.repeat(32),container:{running:true,exists:true},gameMode:'mount',sourceGame:'/home/player/Games/Morrowind — Game of the Year Edition/Original game installation with user modifications',storageDirectory:'/home/player/Games/AstraBridge/Managed runtime storage for Morrowind playthroughs',recordingsDirectory:'/home/player/Videos/AstraBridge/Recordings from extended playthroughs and exploration sessions'};
 let configuration={data_relative:'Data Files',encoding:'win1251',content:['Morrowind.esm','Tribunal.esm','Bloodmoon.esm'],archives:['Morrowind.bsa','Tribunal.bsa','Bloodmoon.bsa'],difficulty:-100,best_attack:true,delay_tribunal:true,sound:true,graphics_gpu:'auto',encoding_gpu:'auto',recording_encoder:'auto',vaapi_device:null};
 const atlas={supported:true,svg:'/v1/artifacts/atlas',location:'Seyda Neen',recorded_points:426,spaces:[{ref:'exterior',location:'Seyda Neen and the Bitter Coast'},{ref:'house',location:'Balmora, Caius Cosades’ House — a long location label'}],nodes:Array.from({length:22},(_,i)=>({ref:'node-'+i,label:i===0?'The lighthouse entrance beside the wooden bridge':'Visited point A'+(i+1),location:'Seyda Neen',names:['Lighthouse entrance','Wooden bridge'],distance_m:i*2.35,visits:i+1,can_revisit:true,route_distance_m:14.8+i,landmarks:['A narrow walkway beside the shore','The door facing the wooden bridge']})),transitions:[{from:'node-0',to:'node-2',from_space:'exterior',to_space:'house',door:{name:'Caius Cosades’ House'},source:'observed_door_transition'}]};
 Object.assign(atlas,{map_markers:[{ref:'node-0',label:'A1',x:.125,y:460/600},{ref:'node-1',label:'A2',x:.5,y:.5},{ref:'node-2',label:'A3',x:.725,y:140/600}],map_bounds:{left:.125,right:.725,top:140/600,bottom:460/600}});
 if(atlasData)Object.assign(atlas,atlasData,{svg:'/v1/artifacts/atlas'});
 const recordings=Array.from({length:18},(_,i)=>({id:String(i),name:i===0?'20261002-084101-exploring-the-coast-and-returning-to-balmora.mp4':`2026100${i%9+1}-120000-session-${i}.mp4`,bytes:1400000000+i*1000,created:1790000000-i*3600,video:'/v1/artifacts/video',metadata:'/v1/artifacts/meta'}));
 const catalog=()=>({profiles:structuredClone(profiles),active:structuredClone(profiles.find(p=>p.active))});
 const emit=()=>handlers.forEach(h=>h({type:'status',data:structuredClone(runtime)}));
 window.fixture={state,runtime,configuration,atlas,recordings,profiles,calls:[],emit,mediaURL:null,empty:false};
 const mapSrc=value=>value.startsWith('astra-artifact://')?(value.split('?')[0].endsWith('atlas')?'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg)+'#'+value.split('?')[1]:window.fixture.mediaURL):value;
 const setAttribute=Element.prototype.setAttribute;
 Element.prototype.setAttribute=function(name,value){return setAttribute.call(this,name,name==='src'&&(this instanceof HTMLMediaElement||this instanceof HTMLImageElement)?mapSrc(String(value)):value);};
 for(const [proto,key] of [[HTMLMediaElement.prototype,'src'],[HTMLImageElement.prototype,'src']]){const d=Object.getOwnPropertyDescriptor(proto,key);Object.defineProperty(proto,key,{...d,set(value){d.set.call(this,mapSrc(String(value)));}});}
 window.astra={subscribe:fn=>{handlers.push(fn);return()=>{};},input:()=>{},invoke:async(op,args={})=>{
  window.fixture.calls.push({op,args});
  if(op==='status')return structuredClone(state);
  if(op==='atlas')return window.fixture.empty?{supported:false}:structuredClone(atlas);
  if(op==='recordings')return window.fixture.empty?[]:structuredClone(recordings);
  if(op==='configuration')return structuredClone(configuration);
  if(op==='configure'){Object.assign(configuration,args);return structuredClone(configuration);}
  if(op==='gpus')return [{id:'pci:0000:01:00.0',name:'NVIDIA GeForce RTX 3060 Laptop GPU',pci:'0000:01:00.0',accessible:true,render_selectable:true},{id:'pci:0000:06:00.0',name:'AMD Radeon 680M integrated graphics',pci:'0000:06:00.0',accessible:true,render_selectable:true}];
  if(op==='logs')return {names:['daemon.log','weston.log','engine-private.log'],text:window.fixture.empty?'':Array.from({length:90},(_,i)=>`12:30:${String(i%60).padStart(2,'0')} INFO [runtime] Native frame stream ready; waiting for a gameplay command. Frame ${i*60}`).join('\n')};
  if(op==='environment')return {version:'0.3.0-dev',graphics:{hardware_accelerated:true,renderer:'AMD Radeon 680M'},runtime_api:1,ffmpeg:{version:'9.0.2'}};
  if(op==='sessions')return [{event:'engine_started',time:1790000000},{event:'agent_connected',name:'Gameplay agent',time:1790000050}];
  if(op==='artifact-json')return {encoder:'h264_vaapi',width:1920,height:1080,fps:60,duration:125,frames:7500,hardware_accelerated:true,quality_mode:'cqp',quality:18,audio_sample_rate:48000,diagnostics:{ring_dropped_frames:0,encoder_queue_peak:1},environment:{renderer:'AMD Radeon 680M',ffmpeg_version:'9.0.2'}};
  if(op==='profiles')return catalog();
  if(op==='profile'){
   if(runtime.running)throw Error('Stop the game before managing profiles');
   let row=profiles.find(p=>p.id===args.id);
   if(args.operation==='create'||args.operation==='duplicate'){row={id:'profile-'+counter++,name:args.name,active:false,created:1790000000};profiles.push(row);}
   if(args.operation==='rename')row.name=args.name;
   if(args.operation==='switch'){profiles.forEach(p=>p.active=p===row);runtime.profile=row;emit();}
   return {...catalog(),result:row};
  }
  if(op==='stop-game'){runtime.running=false;emit();}
  if(op==='start'){runtime.running=true;emit();}
  if(op==='stop'){runtime.running=false;state.container.running=false;emit();}
  if(op==='choose-directory')return '/home/player/Games/Morrowind';
  if(op==='prerequisites')return {available:true};
  if(op==='record'){runtime.recording=args.action==='start'?{recording:true,duration:10}:null;emit();}
  if(op==='replay-info')return {ready:false,active:false,duration:0};
  return {};
 }};
 window.fixture.ready=(async()=>{
  const c=document.createElement('canvas');c.width=1280;c.height=720;const ctx=c.getContext('2d');let img;
  if(hasFrame){img=new Image();img.src='/fixture-frame.png';await img.decode();}
  const draw=()=>{if(img)ctx.drawImage(img,0,0,c.width,c.height);else {ctx.fillStyle='#263846';ctx.fillRect(0,0,c.width,c.height);}};
  draw();const stream=c.captureStream(10),rec=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'}),parts=[];
  rec.ondataavailable=e=>parts.push(e.data);const done=new Promise(resolve=>rec.onstop=resolve);rec.start();const timer=setInterval(draw,100);await new Promise(r=>setTimeout(r,1000));rec.stop();await done;clearInterval(timer);stream.getTracks().forEach(t=>t.stop());window.fixture.mediaURL=URL.createObjectURL(new Blob(parts,{type:'video/webm'}));
 })();
},{svg,hasFrame:Boolean(process.env.ASTRA_TEST_FRAME),atlasData});
async function shot(name){
 const data=await page.evaluate(()=>{
  const main=document.querySelector('main'),card=document.querySelector('.card');
  return {width:innerWidth,height:innerHeight,document:[document.documentElement.scrollWidth,document.documentElement.scrollHeight],mainOverflow:[main.scrollWidth-main.clientWidth,main.scrollHeight-main.clientHeight],cardOverflow:card?[card.scrollWidth-card.clientWidth,card.scrollHeight-card.clientHeight]:[],
   media:[...document.querySelectorAll('.atlas-image,video.playback')].map(e=>{const b=e.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height};}),
   regions:[...document.querySelectorAll('.settings-fields,.setup-fields,.profile-detail')].map(e=>({name:e.className,overflow:e.scrollHeight-e.clientHeight})),
   controls:[...document.querySelectorAll('.card-footer button,.section-heading button,.profile-actions button,.container-management button')].filter(e=>e.getClientRects().length).map(e=>{const b=e.getBoundingClientRect();return {label:e.textContent.trim(),x:b.x,y:b.y,right:b.right,bottom:b.bottom};})};
 });
 await page.screenshot({path:join(output,name+'.png'),animations:'disabled'});results.push({name,...data});
 if(!process.argv.includes('--baseline')){
  assert.ok(data.document[0]<=data.width&&data.document[1]<=data.height,name+' document overflow');
  assert.ok(data.mainOverflow.every(n=>n<=1)&&data.cardOverflow.every(n=>n<=1),name+' clipped card');
  for(const c of data.controls)assert.ok(c.x>=0&&c.y>=0&&c.right<=data.width&&c.bottom<=data.height,name+' offscreen '+c.label);
 }
}
async function nav(name){await page.getByRole('navigation').getByRole('button',{name,exact:true}).click();await page.getByRole('heading',{level:1,name,exact:true}).waitFor();await page.waitForFunction(()=>!document.querySelector('.working'));}
try{
 await page.goto(process.env.ASTRA_UI_URL??'http://127.0.0.1:4178');await page.evaluate(()=>window.fixture.ready);
 for(const [width,height] of [[1280,720],[960,680],[1920,1080]]){
  await page.setViewportSize({width,height});const suffix=width.toString();
  await nav('Atlas');await page.getByRole('button',{name:'Visited points',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.atlas-image')?.naturalWidth>0);await shot('atlas-'+suffix);
  await page.locator('.atlas-card .node-row').first().click();await shot('atlas-details-'+suffix);
  if(!process.argv.includes('--baseline')){
   const viewportHeight=page.viewportSize().height;const height=await page.locator('.atlas-canvas').evaluate(e=>e.clientHeight);assert.ok(height>=viewportHeight*.55,'Atlas must keep substantial height');
   await page.getByRole('button',{name:'Zoom in',exact:true}).click();await page.getByRole('button',{name:'Zoom in',exact:true}).click();await shot('atlas-zoom-'+suffix);
   await page.getByRole('button',{name:/^Fit ·/}).click();
   if(await page.locator('.atlas-marker').count()){
    const fitted=await page.locator('.atlas-canvas').evaluate(canvas=>{const b=canvas.getBoundingClientRect();return [...canvas.querySelectorAll('.atlas-marker')].every(e=>{const r=e.getBoundingClientRect();return r.x+r.width/2>=b.x&&r.x+r.width/2<=b.right&&r.y+r.height/2>=b.y&&r.y+r.height/2<=b.bottom;});});assert.ok(fitted,'Fit must show every returned marker');
    await page.locator('.atlas-marker').nth(1).click();assert.equal(await page.locator('.atlas-marker.selected').count(),1);await page.getByRole('button',{name:'Locate on map',exact:true}).click();await shot('atlas-point-'+suffix);await page.getByRole('button',{name:/^Fit ·/}).click();
    const canvas=await page.locator('.atlas-canvas').boundingBox(),before=await page.locator('.atlas-image-stage').getAttribute('style');
    await page.mouse.move(canvas.x+30,canvas.y+30);await page.mouse.down();await page.mouse.move(canvas.x+90,canvas.y+60,{steps:3});await page.mouse.up();assert.notEqual(await page.locator('.atlas-image-stage').getAttribute('style'),before,'Drag must pan the map');await page.getByRole('button',{name:/^Fit ·/}).click();
   }
   await page.getByRole('button',{name:'Transitions',exact:true}).click();await shot('atlas-transitions-'+suffix);
   assert.equal(await page.locator('.atlas-canvas').evaluate(e=>e.clientHeight),height,'Sidebar changed map height');
   await page.getByRole('button',{name:'Expand map',exact:true}).click();await shot('atlas-expanded-'+suffix);await page.getByRole('button',{name:'Show map sidebar',exact:true}).click();
   const previous=await page.locator('.atlas-image').getAttribute('src');await page.getByLabel('Map area',{exact:true}).selectOption('100');await page.waitForFunction(()=>!document.querySelector('.working'));assert.notEqual(await page.locator('.atlas-image').getAttribute('src'),previous,'Area change must reload the map image');await page.getByLabel('Map area',{exact:true}).selectOption('35');
  }
  await nav('Recordings');await page.locator('.recordings-card .node-row').first().click();await page.waitForFunction(()=>document.querySelector('video.playback')?.readyState>=2);await shot('recordings-'+suffix);
  const videoHeight=await page.locator('video.playback').evaluate(e=>e.clientHeight);await page.getByText('Recording metadata',{exact:true}).click();await shot('recordings-metadata-'+suffix);
  if(!process.argv.includes('--baseline'))assert.equal(await page.locator('video.playback').evaluate(e=>e.clientHeight),videoHeight,'Metadata must not shrink the video');
  await nav('Profiles');await shot('profiles-'+suffix);
  await page.locator('.profile-grid .node-row').nth(1).click();await page.getByRole('button',{name:'Duplicate profile',exact:true}).click();await shot('profiles-copy-'+suffix);
  await page.evaluate(()=>{window.fixture.runtime.running=true;window.fixture.emit();});await shot('profiles-locked-'+suffix);
  if(!process.argv.includes('--baseline'))assert.ok(await page.getByRole('button',{name:'Cancel',exact:true}).isEnabled(),'Cancel must remain usable while the game is running');
  await page.evaluate(()=>{window.fixture.runtime.running=false;window.fixture.emit();});
  await nav('Settings');for(const label of ['Game data','Gameplay','Graphics and recording']){await page.getByRole('button',{name:label,exact:true}).click();await shot('settings-'+label.split(' ')[0].toLowerCase()+'-'+suffix);}
  await nav('Diagnostics');for(const label of ['Logs','Environment','Sessions']){await page.getByRole('button',{name:label,exact:true}).click();await shot('diagnostics-'+label.toLowerCase()+'-'+suffix);}
  await nav('Setup');await page.getByRole('button',{name:'Runtime',exact:true}).click();await page.getByText('Image identity',{exact:true}).click();await shot('setup-runtime-'+suffix);
  await page.getByRole('button',{name:'Storage and skill',exact:true}).click();await shot('setup-storage-'+suffix);
 }
 await page.setViewportSize({width:960,height:680});
 await page.evaluate(()=>window.fixture.empty=true);await nav('Atlas');await shot('atlas-empty');await nav('Recordings');await shot('recordings-empty');
 await page.evaluate(()=>{window.fixture.state.updatePending=true;window.fixture.state.previousRuntime={version:'0.2.2',created:1790000000000};});await nav('Setup');await page.getByRole('button',{name:'Runtime',exact:true}).click();await page.getByRole('button',{name:'Recover interrupted update',exact:true}).waitFor();await shot('setup-recovery');
 await page.evaluate(()=>{window.fixture.state.installed=false;window.fixture.state.runtime={};});await page.waitForFunction(()=>document.querySelector('h2')?.textContent==='Install AstraBridge runtime');await shot('setup-new-game');
 await page.getByPlaceholder('Choose your existing Morrowind folder').fill('/home/player/Games/Morrowind');await page.getByRole('button',{name:'Next: Storage',exact:true}).click();await shot('setup-new-storage');
 assert.deepEqual(errors,[]);console.log(JSON.stringify(results.filter(r=>r.cardOverflow.some(n=>n>1)||r.mainOverflow.some(n=>n>1)||r.regions.some(x=>x.overflow>1)),null,2));
}finally{await writeFile(join(output,'layout.json'),JSON.stringify({results,errors},null,2));await browser.close();}
