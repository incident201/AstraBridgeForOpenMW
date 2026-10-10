import {request,type IncomingMessage} from 'node:http';
import {Readable} from 'node:stream';

// Game commands can withhold headers for the entire caller-selected action.
// Native HTTP leaves that wait to the daemon watchdog and caller's AbortSignal,
// rather than fetch's independent five-minute header/body deadlines.
export async function gameCommandHttp(url:string,init:RequestInit={}):Promise<Response>{
  if(init.body!=null&&typeof init.body!=='string')throw new TypeError('Game commands require a JSON string body');
  const signal=init.signal;
  signal?.throwIfAborted();
  return new Promise((resolve,reject)=>{
    let incoming:IncomingMessage|undefined;
    const cleanup=()=>signal?.removeEventListener('abort',abort);
    const abort=()=>{
      const reason=signal!.reason;
      const error=reason instanceof Error?reason:Object.assign(new DOMException('The operation was aborted.','AbortError'),{cause:reason});
      incoming?.destroy(error);
      outgoing.destroy(error);
      reject(reason);
    };
    const outgoing=request(url,{method:init.method??'GET',headers:Object.fromEntries(new Headers(init.headers)),
      agent:false,timeout:0},response=>{
      incoming=response;
      response.once('close',cleanup);
      try{
        const headers=new Headers();
        for(let i=0;i<response.rawHeaders.length;i+=2)headers.append(response.rawHeaders[i],response.rawHeaders[i+1]);
        const status=response.statusCode??200;
        const body=init.method?.toUpperCase()==='HEAD'||[204,205,304].includes(status)?null:
          Readable.toWeb(response) as ReadableStream<Uint8Array>;
        if(body===null)response.resume();
        resolve(new Response(body,{status,statusText:response.statusMessage,headers}));
      }catch(error){
        response.destroy();outgoing.destroy();cleanup();reject(error);
      }
    });
    outgoing.once('error',error=>{cleanup();reject(signal?.aborted?signal.reason:error);});
    signal?.addEventListener('abort',abort,{once:true});
    outgoing.end(init.body);
  });
}
