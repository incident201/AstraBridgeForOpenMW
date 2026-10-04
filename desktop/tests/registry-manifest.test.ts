import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {imageLayers} from '../main/runtime/RegistryManifest';

test('optional OCI lookup chooses Linux amd64 and ignores invalid layer counters',async()=>{
 const id='sha256:'+'a'.repeat(64),layer={digest:'sha256:'+'b'.repeat(64),size:12345};const requests:string[]=[];
 const server=createServer((req,res)=>{
  requests.push(req.url!);res.setHeader('Content-Type','application/json');
  if(req.url?.endsWith('/latest'))res.end(JSON.stringify({manifests:[{digest:'wrong',platform:{os:'linux',architecture:'arm64'}},{digest:id,platform:{os:'linux',architecture:'amd64'}}]}));
  else res.end(JSON.stringify({layers:[layer,{digest:'invalid',size:4},{digest:layer.digest,size:-2}]}));
 });
 await new Promise<void>(r=>server.listen(0,'127.0.0.1',r));
 try{
  const port=(server.address() as any).port;
  assert.deepEqual(await imageLayers(`127.0.0.1:${port}/image:latest`),[layer]);
  assert.equal(requests.length,2);assert.ok(requests[1].endsWith(encodeURIComponent(id)));
 }finally{await new Promise<void>(r=>server.close(()=>r()));}
});
test('registry metadata failure leaves native pull available',async()=>{
 const server=createServer((_req,res)=>{res.writeHead(503);res.end();});
 await new Promise<void>(r=>server.listen(0,'127.0.0.1',r));
 try{assert.deepEqual(await imageLayers(`127.0.0.1:${(server.address() as any).port}/image:v1`),[]);}
 finally{await new Promise<void>(r=>server.close(()=>r()));}
});
