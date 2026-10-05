import {pathToFileURL} from 'node:url';

interface FolderShell {
  openPath(path:string):Promise<string>;
  openExternal(url:string):Promise<void>;
}

/** Open a host directory without leaving its renderer request pending forever. */
export async function openFolder(directory:string,shell:FolderShell,
  {platform=process.platform,timeoutMs=10000}:{platform?:string;timeoutMs?:number}={}){
  let timer:ReturnType<typeof setTimeout>|undefined;
  try{
    await Promise.race([
      new Promise<never>((_,reject)=>{
        timer=setTimeout(()=>reject(new Error('The system did not respond to the request.')),timeoutMs);
      }),
      Promise.resolve().then(async()=>{
        // Electron 42.11.3's Linux OpenPath drops the completion callback after
        // launching xdg-open. OpenExternal completes its own callback and also
        // accepts local file URLs. Encoding keeps spaces, #, % and Unicode safe.
        if(platform==='linux')await shell.openExternal(pathToFileURL(directory).href);
        else{
          const error=await shell.openPath(directory);
          if(error)throw new Error(error);
        }
      }),
    ]);
  }catch(error){
    throw new Error(`Could not open folder "${directory}": ${error instanceof Error?error.message:String(error)}`);
  }finally{if(timer)clearTimeout(timer);}
}
