import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer,type RequestListener} from 'node:http';
import {once} from 'node:events';
import {setTimeout as delay} from 'node:timers/promises';
import {Core,type Installation} from '../main/core';
import {gameCommandHttp} from '../main/game-command-http';

async function fixture(handler:RequestListener){
  const server=createServer(handler);server.listen(0,'127.0.0.1');await once(server,'listening');
  const address=server.address();assert.ok(address&&typeof address!=='string');
  const config={apiPort:address.port,token:'api-token',agentToken:'agent-token'} as Installation;
  return {core:new Core('/unused'),config,url:`http://127.0.0.1:${address.port}/v1/game/command`,
    async close(){server.closeAllConnections();await new Promise<void>((resolve,reject)=>server.close(error=>error?reject(error):resolve()));}};
}

test('Core game commands keep authentication and complete delayed headers and chunked JSON',async()=>{
  const command={op:'navigate',args:{ref:'destination',seconds:900}};
  let received:unknown,headers:Record<string,unknown>={};
  const f=await fixture(async(request,response)=>{
    headers=request.headers;let body='';for await(const chunk of request)body+=chunk;
    received=JSON.parse(body);
    await delay(30);response.writeHead(200,{'Content-Type':'application/json','X-Astra-Test':'preserved'});
    response.write('{"ok":true,"result":{"message":');
    await delay(30);response.end('"Готово","elapsed":900}}');
  });
  const original=globalThis.fetch;
  globalThis.fetch=async()=>{throw Error('Game command reached fetch');};
  try{
    const response=await f.core.fetch('/v1/game/command',{method:'POST',headers:{'Content-Type':'application/json','X-Test':'custom'},
      body:JSON.stringify(command),signal:AbortSignal.timeout(1000)},f.config);
    assert.equal(response.status,200);assert.equal(response.headers.get('X-Astra-Test'),'preserved');
    assert.deepEqual(await response.json(),{ok:true,result:{message:'Готово',elapsed:900}});
    assert.deepEqual(received,command);assert.equal(headers.authorization,'Bearer api-token');
    assert.equal(headers['x-astra-session'],'agent-token');assert.equal(headers['x-test'],'custom');
    assert.equal(headers['content-type'],'application/json');
  }finally{globalThis.fetch=original;await f.close();}
});

test('ordinary queries, artifacts and WebRTC continue to use fetch',async()=>{
  const core=new Core('/unused'),calls:string[]=[],config={apiPort:1,token:'api-token',agentToken:'agent-token'} as Installation;
  const original=globalThis.fetch;
  globalThis.fetch=async(url,init)=>{
    calls.push(String(url));assert.equal(new Headers(init?.headers).get('Authorization'),'Bearer api-token');
    return new Response('{"ok":true,"result":{}}');
  };
  try{
    for(const path of ['/health','/v1/game/schema','/v1/artifacts/'+'a'.repeat(32),'/v1/runtime/live/whep'])
      await core.fetch(path,{},config);
    assert.equal(calls.length,4);
  }finally{globalThis.fetch=original;}
});

test('Core API preserves the full HTTP error JSON and request receipt',async()=>{
  const packet={ok:false,error:'game_operation_timeout',message:'Action result is unknown',request_id:'long-route',retryable:false};
  const f=await fixture((_request,response)=>{
    response.writeHead(409,{'Content-Type':'application/json'});
    const body=JSON.stringify(packet);response.write(body.slice(0,20));response.end(body.slice(20));
  });
  try{
    await assert.rejects(()=>f.core.api('/v1/game/command','POST',{op:'go',args:{}},f.config),
      (error:any)=>{assert.equal(error.message,packet.message);assert.deepEqual(error.details,packet);return true;});
  }finally{await f.close();}
});

test('an already aborted request fails without sending the command',async()=>{
  let requests=0;const f=await fixture((_request,response)=>{requests++;response.end('{}');});
  const controller=new AbortController(),reason=Error('cancelled before send');controller.abort(reason);
  try{
    await assert.rejects(()=>gameCommandHttp(f.url,{signal:controller.signal}),error=>error===reason);
    assert.equal(requests,0);
  }finally{await f.close();}
});

test('the caller timeout cancels a game command waiting for headers',async()=>{
  let received!:()=>void;const requestReceived=new Promise<void>(resolve=>received=resolve);
  let disconnected!:()=>void;const connectionClosed=new Promise<void>(resolve=>disconnected=resolve);
  const f=await fixture((request,_response)=>{request.socket.once('close',disconnected);received();});
  try{
    const result=f.core.api('/v1/game/command','POST',{op:'navigate',args:{seconds:900}},f.config,100);
    await requestReceived;
    await assert.rejects(()=>result,(error:any)=>error.name==='TimeoutError');
    await connectionClosed;
  }finally{await f.close();}
});

test('cancellation after headers interrupts a pending body read and closes the connection',async()=>{
  let disconnected!:()=>void;const connectionClosed=new Promise<void>(resolve=>disconnected=resolve);
  const f=await fixture((request,response)=>{
    request.socket.once('close',disconnected);response.writeHead(200,{'Content-Type':'application/json'});response.write('{"ok":');
  });
  const controller=new AbortController(),reason=Error('cancelled while reading');
  try{
    const response=await gameCommandHttp(f.url,{signal:controller.signal});
    const body=response.json();controller.abort(reason);
    await assert.rejects(()=>body,error=>error===reason);await connectionClosed;
  }finally{await f.close();}
});

test('connection failures before headers and during JSON reads are reported',async()=>{
  for(const afterHeaders of [false,true]){
    let disconnect!:()=>void;
    const f=await fixture((_request,response)=>{
      if(afterHeaders){
        response.writeHead(200,{'Content-Type':'application/json'});response.write('{"ok":true,');disconnect=()=>response.destroy();
      }else response.destroy();
    });
    try{
      if(afterHeaders){
        const response=await gameCommandHttp(f.url),body=response.json();disconnect();await assert.rejects(()=>body);
      }else await assert.rejects(()=>gameCommandHttp(f.url));
    }finally{await f.close();}
  }
});
