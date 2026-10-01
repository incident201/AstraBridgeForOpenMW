import {contextBridge,ipcRenderer} from 'electron';
contextBridge.exposeInMainWorld('astra',{
  invoke:(operation:string,args?:unknown)=>ipcRenderer.invoke('astra:invoke',operation,args),
  input:(message:unknown)=>ipcRenderer.send('astra:input',message),
  subscribe:(callback:(message:unknown)=>void)=>{
    const handler=(_event:unknown,message:unknown)=>callback(message);
    ipcRenderer.on('astra:event',handler);return ()=>ipcRenderer.removeListener('astra:event',handler);
  },
});
