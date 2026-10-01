/** Run against a disposable installation with an explicitly selected save fixture. */
import {_electron as electron} from '@playwright/test';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
process.chdir(fileURLToPath(new URL('..',import.meta.url)));
const configPath=process.env.ASTRA_CONFIG,output=process.env.ASTRA_TEST_OUTPUT,save=process.env.ASTRA_TEST_SAVE;
if(!configPath||!output||!save)throw Error('Set ASTRA_CONFIG, ASTRA_TEST_OUTPUT and ASTRA_TEST_SAVE');
const cfg=JSON.parse(await readFile(configPath,'utf8')),stamp=Date.now().toString(36),created=[],report={};
let app,page,token,original;await mkdir(output,{recursive:true});
async function raw(path,data,method=data===undefined?'GET':'POST'){
 const response=await fetch(`http://127.0.0.1:${cfg.apiPort}${path}`,{method,signal:AbortSignal.timeout(120000),
 headers:{Authorization:'Bearer '+cfg.token,'Content-Type':'application/json',...(token?{'X-Astra-Session':token}:{})},...(data===undefined?{}:{body:JSON.stringify(data)})});
 return response.json();
}
async function api(path,data){const value=await raw(path,data);if(!value.ok)throw Error(JSON.stringify(value));return value.result;}
const profile=(op,args)=>api('/v1/runtime/profiles/'+op,args),game=(op,args={})=>api('/v1/game/command',{op,args});
async function start(id,load=true){
 await api('/v1/runtime/engine/start',{profile:id});token=(await api('/v1/agent/connect',{name:'Profile fixture',profile:id})).session_token;
 const saves=(await game('saves')).saves;
 if(load){const selected=saves.filter(s=>s.description===save);assert.equal(selected.length,1);await game('load',{ref:selected[0].ref});}
 return saves;
}
async function stop(){await api('/v1/runtime/engine/stop',{});token=undefined;}
try{
 original=(await api('/v1/runtime/profiles')).active.id;await stop();
 const source=(await profile('duplicate',{id:original,name:'Fixture source '+stamp})).result.id;created.push(source);
 await profile('switch',{id:source});await start(source);
 const note='Isolated note '+stamp,label='Fixture landmark '+stamp;
 await game('knowledge',{action:'add',kind:'note',text:note});await game('observe');await game('remember',{label,note:'Profile attachment'});
 await api('/v1/runtime/recording/start',{});await game('act',{yaw:10,seconds:2});await api('/v1/runtime/recording/stop',{});
 const rows=await api('/v1/runtime/recordings');assert.equal(rows.length,1);
 const video=await fetch(`http://127.0.0.1:${cfg.apiPort}${rows[0].video}`,{headers:{Authorization:'Bearer '+cfg.token,Range:'bytes=0-1'}});
 assert.ok(video.headers.get('X-Astra-Artifact-Relative-Path').startsWith(source+'/'));await video.arrayBuffer();
 for(const op of ['create','rename','switch','duplicate','delete']){
  const result=await raw('/v1/runtime/profiles/'+op,{id:source,name:'Rejected'});assert.equal(result.error,'stop_game_before_managing_profiles');
 }
 await stop();
 app=await electron.launch({executablePath:resolve('node_modules/electron/dist/electron'),args:[resolve('.'),'--ozone-platform=x11'],
  env:{...process.env,ASTRA_RESOURCES:resolve('resources'),ASTRA_DESKTOP_DATA:join(resolve(output),'userdata')}});
 await app.evaluate(({dialog})=>{globalThis.confirmations=[];globalThis.confirmChoice=0;dialog.showMessageBox=async(...args)=>{
  globalThis.confirmations.push(args.at(-1));return {response:globalThis.confirmChoice,checkboxChecked:false};};});
 page=await app.firstWindow();await page.setViewportSize({width:960,height:680});
 await page.getByRole('navigation').getByRole('button',{name:'Profiles',exact:true}).click();
 await page.getByRole('button',{name:'Duplicate profile',exact:true}).click();
 const copyName='Fixture copy '+stamp;await page.getByLabel('Profile name',{exact:true}).fill(copyName);
 await page.getByRole('button',{name:'Create copy',exact:true}).click();
 await page.getByRole('heading',{name:copyName,exact:true}).waitFor();
 const copy=(await api('/v1/runtime/profiles')).profiles.find(p=>p.name===copyName).id;created.push(copy);
 await page.getByRole('button',{name:'Rename',exact:true}).click();await page.getByLabel('Profile name',{exact:true}).fill(copyName+' renamed');
 await page.getByRole('button',{name:'Save name',exact:true}).click();await page.getByRole('heading',{name:copyName+' renamed',exact:true}).waitFor();
 await page.getByRole('button',{name:'Use this profile',exact:true}).click();
 await page.getByRole('button',{name:'Active profile',exact:true}).waitFor();
 assert.equal((await api('/v1/runtime/profiles')).active.id,copy);
 await page.getByRole('button',{name:'New profile',exact:true}).click();await page.getByLabel('Profile name',{exact:true}).fill('Fixture fresh '+stamp);
 await page.getByRole('button',{name:'Create profile',exact:true}).click();await page.getByRole('heading',{name:'Fixture fresh '+stamp,exact:true}).waitFor();
 const fresh=(await api('/v1/runtime/profiles')).profiles.find(p=>p.name==='Fixture fresh '+stamp).id;created.push(fresh);
 await page.getByRole('button',{name:'Use this profile',exact:true}).click();await page.getByRole('button',{name:'Active profile',exact:true}).waitFor();
 assert.equal((await raw('/v1/runtime/engine/start',{profile:copy})).error,'profile_mismatch');assert.equal((await api('/v1/runtime/status')).running,false);
 assert.deepEqual(await start(fresh,false),[]);assert.deepEqual((await game('knowledge',{action:'list'})).items,[]);
 assert.deepEqual((await game('recall',{archived:true})).places,[]);assert.deepEqual(await api('/v1/runtime/recordings'),[]);
 report.freshIsEmpty=true;await stop();
 await profile('switch',{id:copy});await start(copy);
 assert.ok((await game('knowledge',{action:'list',query:note})).items.some(n=>n.text===note));
 const recalled=await game('recall',{query:label,archived:true});assert.equal(recalled.places.length,1);
 const attachment=recalled.places[0].views.find(v=>v.screenshot)?.screenshot;assert.ok(attachment?.startsWith('/v1/artifacts/'));
 await stop();await profile('delete',{id:source});created.splice(created.indexOf(source),1);
 await start(copy);assert.ok((await game('knowledge',{action:'list',query:note})).items.some(n=>n.text===note));
 const retained=(await game('recall',{query:label,archived:true})).places[0].views.find(v=>v.screenshot)?.screenshot;
 const image=await fetch(`http://127.0.0.1:${cfg.apiPort}${retained}`,{headers:{Authorization:'Bearer '+cfg.token}});assert.equal(image.status,200);assert.ok((await image.arrayBuffer()).byteLength>100);
 report.copySurvivesSourceDeletion=true;await stop();
 await page.getByRole('navigation').getByRole('button',{name:'Profiles',exact:true}).click();
 await page.getByRole('button',{name:'Delete profile',exact:true}).click();await page.waitForTimeout(300);
 assert.ok((await api('/v1/runtime/profiles')).profiles.some(p=>p.id===fresh),'Cancel deleted the selected profile');
 await app.evaluate(()=>globalThis.confirmChoice=1);await page.getByRole('button',{name:'Delete profile',exact:true}).click();
 await page.waitForTimeout(400);assert.ok(!(await api('/v1/runtime/profiles')).profiles.some(p=>p.id===fresh));created.splice(created.indexOf(fresh),1);
 report.confirmedDeletion=true;await page.screenshot({path:join(output,'profiles.png')});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollHeight<=innerHeight));report.passed=true;console.log(JSON.stringify(report));
}catch(error){report.error=String(error);if(page)await page.screenshot({path:join(output,'failure.png')}).catch(()=>{});throw error;}
finally{
 await stop().catch(()=>{});if(original)await profile('switch',{id:original}).catch(()=>{});
 for(const id of created)await profile('delete',{id}).catch(()=>{});
 if(app){await app.evaluate(()=>globalThis.confirmChoice=1).catch(()=>{});await app.close().catch(()=>{});}
 await writeFile(join(output,'result.json'),JSON.stringify(report,null,2)+'\n');
}
