import {app,BrowserWindow,dialog,ipcMain,net,protocol,shell} from 'electron';
import {dirname,join,resolve,sep} from 'node:path';
import {pathToFileURL} from 'node:url';
import {pipeline} from 'node:stream/promises';
import {Readable} from 'node:stream';
import {createWriteStream} from 'node:fs';
import WebSocket from 'ws';
import {Core} from './core';

if(process.env.ASTRA_DESKTOP_DATA)app.setPath('userData',process.env.ASTRA_DESKTOP_DATA);

protocol.registerSchemesAsPrivileged([
  {scheme:'astra',privileges:{standard:true,secure:true,supportFetchAPI:true}},
  {scheme:'astra-artifact',privileges:{standard:true,secure:true,supportFetchAPI:true,stream:true}},
]);
let window:BrowserWindow|null=null,events:WebSocket|null=null,quitting=false;
let viewerFullscreen=false,previousWindowFullscreen=false;
const resources=process.env.ASTRA_RESOURCES??join(process.resourcesPath,'astra');
const core=new Core(resources,undefined,text=>window?.webContents.send('astra:event',{type:'progress',data:text}));

async function connectEvents(){
  if(events&&events.readyState<=WebSocket.OPEN)return;
  const config=await core.load();if(!config)return;
  events=new WebSocket(`ws://127.0.0.1:${config.apiPort}/v1/events`,{headers:{Authorization:'Bearer '+config.token}});
  events.on('message',data=>{try{window?.webContents.send('astra:event',JSON.parse(data.toString()));}catch{}});
  events.on('error',()=>{});
}
function allowedFrame(url:string){return url.startsWith('astra://app/');}

app.whenReady().then(async()=>{
  const frontend=join(__dirname,'frontend');
  protocol.handle('astra',request=>{
    const url=new URL(request.url);const path=resolve(frontend,'.'+decodeURIComponent(url.pathname==='/'?'/index.html':url.pathname));
    if(url.hostname!=='app'||!path.startsWith(frontend+sep))return new Response('Not found',{status:404});
    return net.fetch(pathToFileURL(path).toString());
  });
  protocol.handle('astra-artifact',async request=>{
    const id=new URL(request.url).hostname;if(!/^[a-f0-9]{32}$/.test(id))return new Response('Not found',{status:404});
    const range=request.headers.get('range');return core.fetch('/v1/artifacts/'+id,{headers:range?{Range:range}:{}});
  });
  ipcMain.handle('astra:invoke',async(event,operation:string,args:any={})=>{
    if(!event.senderFrame||!allowedFrame(event.senderFrame.url))throw new Error('Invalid sender');
    try{
      if(operation==='status'){const result=await core.status();if(result.container?.running)await connectEvents();return result;}
      if(operation==='prerequisites')return core.prerequisites(String(args.storage));
      if(operation==='install')return core.install(args);
      if(['start','stop','restart','update'].includes(operation)){
        const result=await core[operation as 'start'|'stop'|'restart'|'update']();await connectEvents();return result;
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
      if(operation==='skill-export'){
        const result=await dialog.showOpenDialog(window!,{properties:['openDirectory','createDirectory']});if(result.canceled)return null;
        const executable=process.env.APPIMAGE??join(dirname(process.execPath),process.platform==='win32'?'astrabridge.exe':'astrabridge');
        return core.exportSkill(join(result.filePaths[0],'openmw-play'),executable);
      }
      if(operation==='logs')return core.logs(args.name);
      if(operation==='configuration'){
        await core.ensureDaemon();await connectEvents();return core.api('/v1/runtime/config');
      }
      if(operation==='gpus')return core.api('/v1/runtime/gpus');
      if(operation==='configure')return core.api('/v1/runtime/config','PATCH',args);
      if(operation==='stop-game')return core.api('/v1/runtime/engine/stop','POST',{});
      if(operation==='agent-end')return core.api('/v1/runtime/agent/end','POST',{});
      if(operation==='recordings'){await core.ensureDaemon();return core.api('/v1/runtime/recordings');}
      if(operation==='open-recordings-folder'){
        const config=await core.configured();const error=await shell.openPath(config.recordingsDirectory);if(error)throw new Error(error);return config.recordingsDirectory;
      }
      if(operation==='record'){
        if(!['start','stop','status'].includes(args.action))throw new Error('Invalid recording operation');
        return core.api('/v1/runtime/recording/'+args.action,'POST',{});
      }
      if(operation==='atlas'){await core.ensureDaemon();return core.api('/v1/runtime/atlas?'+new URLSearchParams(args).toString());}
      if(operation==='environment')return core.api('/v1/runtime/environment');
      if(operation==='sessions')return core.api('/v1/runtime/sessions');
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
        const response=await core.fetch(args.path);if(!response.ok||!response.body)throw new Error('Artifact unavailable');
        await pipeline(Readable.fromWeb(response.body as any),createWriteStream(choice.filePath));return choice.filePath;
      }
      if(operation==='artifact-json'){
        if(!/^\/v1\/artifacts\/[a-f0-9]{32}$/.test(args.path))throw new Error('Invalid artifact');
        const response=await core.fetch(args.path);if(!response.ok)throw new Error('Artifact unavailable');return response.json();
      }
      throw new Error('Unknown application operation');
    }catch(error){throw new Error((error as Error).message);}
  });
  ipcMain.on('astra:input',(event,message:unknown)=>{
    if(event.senderFrame&&allowedFrame(event.senderFrame.url)&&events?.readyState===WebSocket.OPEN)
      events.send(JSON.stringify(message));
  });
  window=new BrowserWindow({width:1320,height:900,minWidth:960,minHeight:680,title:'AstraBridge',backgroundColor:'#0c1320',
    webPreferences:{preload:join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
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
  if(quitting)return;event.preventDefault();quitting=true;
  events?.close();events=null;
  Promise.race([core.api('/v1/runtime/live','DELETE').catch(()=>{}),new Promise(resolve=>setTimeout(resolve,2000))])
    .finally(()=>app.quit());
});
