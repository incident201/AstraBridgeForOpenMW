import {app,BrowserWindow,dialog,ipcMain,net,protocol,shell,Menu} from 'electron';
import {dirname,join,resolve,sep} from 'node:path';
import {pathToFileURL} from 'node:url';
import {pipeline} from 'node:stream/promises';
import {Readable} from 'node:stream';
import {createWriteStream} from 'node:fs';
import WebSocket from 'ws';
import {Core} from './core';
import {StopSessionRequest} from './stop-session';
import {CloseRequest,type CloseChoice} from './close';
import {localArtifact} from './local-artifact';

app.setName('AstraBridge');
app.commandLine.appendSwitch('autoplay-policy','no-user-gesture-required');
app.setAppUserModelId('io.github.incident201.astrabridge');
if(process.platform==='linux')app.commandLine.appendSwitch('class','astrabridge-desktop');

if(process.env.ASTRA_DESKTOP_DATA)app.setPath('userData',process.env.ASTRA_DESKTOP_DATA);

protocol.registerSchemesAsPrivileged([
  {scheme:'astra',privileges:{standard:true,secure:true,supportFetchAPI:true}},
  {scheme:'astra-artifact',privileges:{standard:true,secure:true,supportFetchAPI:true,stream:true}},
]);
let window:BrowserWindow|null=null,events:WebSocket|null=null,quitting=false,closeApproved=false;
let viewerFullscreen=false,previousWindowFullscreen=false,viewerReview=false;
const resources=process.env.ASTRA_RESOURCES??join(process.resourcesPath,'astra');
const core=new Core(resources,undefined,text=>window?.webContents.send('astra:event',{type:typeof text==='string'?'progress':text.type,data:text}));
async function artifactResponse(path:string,headers:HeadersInit={}){
  const local=await core.recordings.path(path.split('/').pop()!);
  return local?localArtifact(local,new Headers(headers).get('range')):core.fetch(path,{headers});
}

async function connectEvents(){
  if(events&&events.readyState<=WebSocket.OPEN)return;
  const config=await core.load();if(!config)return;
  events=new WebSocket(`ws://127.0.0.1:${config.apiPort}/v1/events`,{headers:{Authorization:'Bearer '+config.token}});
  events.on('message',data=>{try{window?.webContents.send('astra:event',JSON.parse(data.toString()));}catch{}});
  events.on('error',()=>{});
}
function allowedFrame(url:string){return url.startsWith('astra://app/');}
const stopSession=new StopSessionRequest(()=>core.stopSession(),async(reason,prepared)=>{
  const detail=reason==='save_unavailable'?'Saving is unavailable in the current game state.':
    reason==='runtime_unreachable'?'The runtime did not confirm a save.':'The game could not confirm a completed save.';
  const options={type:'warning' as const,title:'Save before stopping',message:'Could not save the game',
    detail:detail+' '+(prepared?'The game is paused and agent control has been released. ':'')+'Stop without saving, or cancel to keep the session open.',
    buttons:['Cancel','Stop without saving'],defaultId:0,cancelId:0,noLink:true};
  const choice=window?await dialog.showMessageBox(window,options):await dialog.showMessageBox(options);
  return choice.response===1;
},()=>core.stop(),token=>core.cancelSessionStop(token));
const closing=new CloseRequest(async()=>{
  if(core.managementBusy)throw new Error('Wait for the install, update or container operation to finish before closing');
  const config=await core.load();if(!config)return false;
  // Missing host tools make runtime state unknown. Still allow Keep running
  // to close Desktop without attempting any container operation.
  try{return (await core.backend(config).inspect(config.name)).running;}catch{return true;}
},async()=>{
  const options={type:'question' as const,title:'Close AstraBridge?',message:'Closing this window does not stop the runtime.',
    detail:'Keep running leaves the container, connected agent and recording session active. Manual control is released when the window closes. Stop session first tries to save the game, then finishes recording and stops the runtime.',
    buttons:['Cancel','Keep running','Stop session'],defaultId:1,cancelId:0,noLink:true};
  const result=window?await dialog.showMessageBox(window,options):await dialog.showMessageBox(options);
  return (['cancel','keep','stop'] as CloseChoice[])[result.response]??'cancel';
},()=>stopSession.request(),async error=>{
  const options={type:'error' as const,title:'AstraBridge is still open',message:'Could not finish closing the runtime.',detail:String(error),buttons:['OK']};
  return window?dialog.showMessageBox(window,options):dialog.showMessageBox(options);
});
async function requestClose(){
  if(closeApproved||quitting)return;
  if(await closing.request()){
    if(closeApproved)return;closeApproved=true;quitting=true;
    events?.close();events=null;
    await Promise.race([core.api('/v1/runtime/live','DELETE').catch(()=>{}),new Promise(resolve=>setTimeout(resolve,2000))]);
    app.quit();
  }
}


app.whenReady().then(async()=>{
  Menu.setApplicationMenu(null);
  const frontend=join(__dirname,'frontend');
  protocol.handle('astra',request=>{
    const url=new URL(request.url);
    if(url.hostname==='app'&&/^\/replay\/[a-f0-9]{32}\/[a-f0-9]+-[a-f0-9]+\/(?:init|[0-9]+)$/.test(url.pathname))
      return core.fetch('/v1/runtime'+url.pathname);
    const path=resolve(frontend,'.'+decodeURIComponent(url.pathname==='/'?'/index.html':url.pathname));
    if(url.hostname!=='app'||!path.startsWith(frontend+sep))return new Response('Not found',{status:404});
    return net.fetch(pathToFileURL(path).toString());
  });
  protocol.handle('astra-artifact',async request=>{
    const id=new URL(request.url).hostname;if(!/^[a-f0-9]{32}$/.test(id))return new Response('Not found',{status:404});
    const range=request.headers.get('range');return artifactResponse('/v1/artifacts/'+id,range?{Range:range}:{});
  });
  ipcMain.handle('astra:invoke',async(event,operation:string,args:any={})=>{
    if(!event.senderFrame||!allowedFrame(event.senderFrame.url))throw new Error('Invalid sender');
    try{
      if(operation==='status'){const result=await core.status();if(result.container?.running)await connectEvents();return result;}
      if(operation==='prerequisites')return core.prerequisites(typeof args.storage==='string'?args.storage:undefined);
      if(operation==='install')return core.install(args);
      if(operation==='reset-setup'||operation==='uninstall'){
        const remove=operation==='uninstall';
        const options={type:'warning' as const,title:remove?'Remove installation?':'Reset setup?',
          message:remove?'Permanently remove this runtime and its managed data?':'Forget this installation and return to setup?',
          detail:remove?'This stops the runtime and deletes its container, profiles, saves, Atlas, notes, recovery snapshots and imported game copy. Original host game files and recordings are kept. Unused runtime images are removed when possible. Other files in the storage folder are not deleted.':
            'This clears only the application’s installation configuration. Existing containers and files are not deleted. Use this when storage was already removed or is no longer accessible. To keep an existing installation, reconnect its storage instead.',
          buttons:['Cancel',remove?'Remove installation and data':'Reset setup'],defaultId:0,cancelId:0,noLink:true};
        const decision=window?await dialog.showMessageBox(window,options):await dialog.showMessageBox(options);
        if(decision.response!==1)return {cancelled:true};
        const result=remove?await core.uninstall():await core.resetSetup();
        events?.close();events=null;return result;
      }
      if(operation==='stop'){const result=await stopSession.request();await connectEvents();return result;}
      if(['start','restart','update'].includes(operation)){
        const result=await core[operation as 'start'|'stop'|'restart'|'update']();await connectEvents();return result;
      }
      if(operation==='remove-container'){
        const options={type:'warning' as const,title:'Remove runtime container?',message:'Remove the AstraBridge runtime container?',
          detail:'This stops the game and finishes the current recording. Game files, saves, Atlas, notes, recordings and settings are kept. You can recreate the container here later.',
          buttons:['Cancel','Remove container'],defaultId:0,cancelId:0,noLink:true};
        const decision=window?await dialog.showMessageBox(window,options):await dialog.showMessageBox(options);
        if(decision.response!==1)return {removed:false};
        const status=await core.removeContainer();events?.close();events=null;return {removed:true,status};
      }
      if(operation==='viewer-fullscreen'){
        if(typeof args.enabled!=='boolean'||!window)throw new Error('Invalid fullscreen request');
        if(args.enabled!==viewerFullscreen){
          viewerFullscreen=args.enabled;
          if(viewerFullscreen){previousWindowFullscreen=window.isFullScreen();window.setFullScreen(true);}
          else if(!previousWindowFullscreen)window.setFullScreen(false);
          window.webContents.send('astra:event',{type:'viewer.fullscreen',enabled:viewerFullscreen});
        }
        return {enabled:viewerFullscreen};
      }
      if(operation==='choose-directory'){
        const result=await dialog.showOpenDialog(window!,{properties:['openDirectory','createDirectory']});return result.canceled?null:result.filePaths[0];
      }
      if(operation==='cli-status')return core.cliStatus();
      if(operation==='cli-install')return core.installCli();
      if(operation==='cli-uninstall')return core.uninstallCli();
      if(operation==='skill-export'){
        const result=await dialog.showOpenDialog(window!,{properties:['openDirectory','createDirectory']});if(result.canceled)return null;
        return core.exportSkill(join(result.filePaths[0],'openmw-play'));
      }
      if(operation==='logs')return core.logs(args.name);
      if(operation==='configuration'){
        await core.ensureDaemon();await connectEvents();return core.api('/v1/runtime/config');
      }
      if(operation==='gpus')return core.api('/v1/runtime/gpus');
      if(operation==='configure')return core.api('/v1/runtime/config','PATCH',args);
      if(operation==='profiles')return core.profiles();
      if(operation==='profile'){
        if(!['create','rename','duplicate','switch','delete'].includes(args.operation))throw new Error('Unknown profile operation');
        if(args.operation==='delete'){
          const catalog=await core.profiles(),profile=catalog.profiles.find((p:any)=>p.id===args.id);
          if(!profile)throw new Error('Profile not found');
          const options={type:'warning' as const,title:'Delete profile?',message:`Permanently delete “${profile.name}”?`,
            detail:'All saves, Atlas, knowledge, notes, settings and session history in this profile will be deleted. This cannot be undone. Game files and video recordings on your computer are kept.',
            buttons:['Cancel','Delete profile'],defaultId:0,cancelId:0,noLink:true};
          const decision=window?await dialog.showMessageBox(window,options):await dialog.showMessageBox(options);
          if(decision.response!==1)return {cancelled:true,...catalog};
        }
        return core.profile(args.operation,{...(args.id?{id:args.id}:{}),...(args.name!==undefined?{name:args.name}:{})});
      }
      if(operation==='stop-game')return core.api('/v1/runtime/engine/stop','POST',{});
      if(operation==='agent-end')return core.api('/v1/runtime/agent/end','POST',{});
      if(operation==='delete-recording'){
        const rows=await core.recordings.list((await core.configured()).recordingsDirectory);
        const row=rows.find(row=>row.id===args.id);
        if(!row)throw new Error('Recording no longer exists. Refresh the list.');
        const options={type:'warning' as const,message:`Delete ${row.name}?`,
          detail:'The video, commentary timeline, metadata and recording logs will be permanently deleted. This cannot be undone.',
          buttons:['Cancel','Delete recording'],defaultId:0,cancelId:0,noLink:true};
        const decision=window?await dialog.showMessageBox(window,options):await dialog.showMessageBox(options);
        if(decision.response!==1)return {cancelled:true};
        return core.deleteRecording(row.id);
      }
      if(operation==='recordings')return core.recordings.list((await core.configured()).recordingsDirectory);
      if(operation==='open-recordings-folder'){
        const directory=await core.recordingsFolder();const error=await shell.openPath(directory);if(error)throw new Error(error);return directory;
      }
      if(operation==='record'){
        if(!['start','stop','status'].includes(args.action))throw new Error('Invalid recording operation');
        return core.api('/v1/runtime/recording/'+args.action,'POST',{});
      }
      if(operation==='atlas'){await core.ensureDaemon();return core.api('/v1/runtime/atlas?'+new URLSearchParams(args).toString());}
      if(operation==='environment')return core.api('/v1/runtime/environment');
      if(operation==='sessions')return core.api('/v1/runtime/sessions');
      if(operation==='replay-info'){
        const info=await core.api('/v1/runtime/replay'+(args.id?'?id='+encodeURIComponent(args.id):''));
        return {...info,events:await core.recordings.replayEvents((await core.configured()).recordingsDirectory,info.name,info.profile_subdirectory)};
      }
      if(operation==='recording-timeline')return core.recordings.timeline(args.path,args.time);
      if(operation==='replay-index'){
        if(!/^[a-f0-9]{32}$/.test(args.id)||! /^[a-f0-9]+-[a-f0-9]+$/.test(args.generation))throw new Error('Invalid replay request');
        return core.api(`/v1/runtime/replay/${args.id}/${args.generation}/index?`+new URLSearchParams(args.after===undefined?{time:String(args.time)}:{after:String(args.after)}));
      }
      if(operation==='viewer-review'){viewerReview=args.enabled===true;return {enabled:viewerReview};}
      if(operation==='live-start')return core.api('/v1/runtime/live','POST',args);
      if(operation==='live-stop')return core.api('/v1/runtime/live','DELETE');
      if(operation==='whep'){
        if(!/^\/v1\/runtime\/live\/whep(?:\/[a-f0-9-]+)?$/.test(args.path)||!['POST','PATCH','DELETE'].includes(args.method))throw new Error('Invalid viewer request');
        const response=await core.fetch(args.path,{method:args.method,headers:{'Content-Type':args.method==='PATCH'?'application/trickle-ice-sdpfrag':'application/sdp'},body:args.body});
        const body=await response.text();if(!response.ok)throw new Error(body);
        return {body,location:response.headers.get('Location')};
      }
      if(operation==='export-artifact'){
        if(!/^\/v1\/artifacts\/[a-f0-9]{32}$/.test(args.path))throw new Error('Invalid artifact');
        const choice=await dialog.showSaveDialog(window!,{defaultPath:String(args.name??'recording.mp4')});
        if(choice.canceled||!choice.filePath)return null;
        const response=await artifactResponse(args.path);if(!response.ok||!response.body)throw new Error('Artifact unavailable');
        await pipeline(Readable.fromWeb(response.body as any),createWriteStream(choice.filePath));return choice.filePath;
      }
      if(operation==='artifact-json'){
        if(!/^\/v1\/artifacts\/[a-f0-9]{32}$/.test(args.path))throw new Error('Invalid artifact');
        const response=await artifactResponse(args.path);if(!response.ok)throw new Error('Artifact unavailable');return response.json();
      }
      throw new Error('Unknown application operation');
    }catch(error){throw new Error((error as Error).message);}
  });
  ipcMain.on('astra:input',(event,message:unknown)=>{
    const value=message as {type?:string;event?:{type?:string}};
    if(viewerReview&&(value?.type==='manual.acquire'||value?.type==='input'&&value.event?.type!=='release'))return;
    if(event.senderFrame&&allowedFrame(event.senderFrame.url)&&events?.readyState===WebSocket.OPEN)
      events.send(JSON.stringify(message));
  });
  window=new BrowserWindow({width:1320,height:900,minWidth:960,minHeight:680,title:'AstraBridge',backgroundColor:'#0c1320',icon:join(resources,'icon.png'),autoHideMenuBar:true,
    webPreferences:{preload:join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
  window.on('close',event=>{if(!closeApproved){event.preventDefault();void requestClose();}});
  window.on('leave-full-screen',()=>{
    if(viewerFullscreen){viewerFullscreen=false;previousWindowFullscreen=false;
      window?.webContents.send('astra:event',{type:'viewer.fullscreen',enabled:false});}
  });
  window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  window.webContents.on('will-navigate',(event,url)=>{if(!allowedFrame(url))event.preventDefault();});
  await window.loadURL('astra://app/index.html');
});
app.on('window-all-closed',()=>app.quit());
app.on('before-quit',event=>{
  if(closeApproved)return;event.preventDefault();void requestClose();
});
