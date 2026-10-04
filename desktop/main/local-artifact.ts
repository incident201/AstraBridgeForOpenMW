import {createReadStream} from 'node:fs';
import {stat} from 'node:fs/promises';
import {Readable} from 'node:stream';
import {extname} from 'node:path';

/** Chromium needs 206 and Content-Range for seeking, including custom protocols. */
export async function localArtifact(path:string,range:string|null=null){
  const {size}=await stat(path);
  const type=extname(path)==='.mp4'?'video/mp4':extname(path)==='.json'?'application/json':'text/plain; charset=utf-8';
  const headers:Record<string,string>={'Content-Type':type,'Accept-Ranges':'bytes','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
  let start=0,end=size-1,status=200;
  if(range){
    const match=/^bytes=(\d*)-(\d*)$/.exec(range);
    if(!match||!size||!match[1]&&!match[2])return new Response(null,{status:416,headers:{...headers,'Content-Range':`bytes */${size}`}});
    if(match[1]){start=Number(match[1]);end=match[2]?Math.min(Number(match[2]),size-1):size-1;}
    else start=Math.max(0,size-Number(match[2]));
    if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start>end||start>=size)
      return new Response(null,{status:416,headers:{...headers,'Content-Range':`bytes */${size}`}});
    status=206;headers['Content-Range']=`bytes ${start}-${end}/${size}`;
  }
  headers['Content-Length']=String(Math.max(0,end-start+1));
  return new Response(size?Readable.toWeb(createReadStream(path,{start,end})) as ReadableStream<Uint8Array>:null,{status,headers});
}
