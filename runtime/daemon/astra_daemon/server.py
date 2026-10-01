from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
import secrets
import uuid
from urllib.parse import quote

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web
from astra_bridge.protocol import BridgeError
from astra_bridge.gpu import inventory
from .commands import catalog
from .runtime import Runtime


def answer(value):return web.json_response({'ok':True,'result':value})


def application(runtime: Runtime, token: str):
    if len(token)<32:raise ValueError('ASTRA_API_TOKEN must contain at least 32 characters')
    commands=catalog();operations={v['operation'] for v in commands.values()}
    @web.middleware
    async def boundary(request, handler):
        if request.path!='/health':
            supplied=request.headers.get('Authorization','')
            if not secrets.compare_digest(supplied,'Bearer '+token):
                return web.json_response({'ok':False,'error':'unauthorized'},status=401)
            origin=request.headers.get('Origin')
            if origin and origin not in {'astra://app','http://127.0.0.1','http://localhost'}:
                return web.json_response({'ok':False,'error':'origin_not_allowed'},status=403)
        try:return await handler(request)
        except BridgeError as exc:return web.json_response({'ok':False,**exc.response()},status=409)
        except (ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
            return web.json_response({'ok':False,'error':'invalid_request','message':str(exc)[:250]},status=400)
        except web.HTTPException:raise
        except Exception:
            logging.exception('Runtime request failed')
            return web.json_response({'ok':False,'error':'runtime_operation_failed'},status=500)

    app=web.Application(middlewares=[boundary],client_max_size=1024*1024)
    sockets=set()
    async def body(request):
        value=await request.json()
        if not isinstance(value,dict):raise ValueError('Expected a JSON object')
        return value
    async def health(request):return answer({'ready':True,'runtime_api':1,'game_api':1,'environment':runtime.build})
    async def gpus(request):return answer(await asyncio.to_thread(inventory))
    async def status(request):return answer(runtime.project(runtime.status()))
    async def engine(request):
        action=request.match_info['action']
        data=await body(request) if request.can_read_body else {}
        if data.keys()-{'gpu'}:raise BridgeError('invalid_arguments')
        if action=='start':return answer(await runtime.start_engine(data.get('gpu')))
        if action=='stop':return answer(await runtime.stop_engine())
        if action=='restart':
            await runtime.stop_engine();return answer(await runtime.start_engine(data.get('gpu')))
        raise web.HTTPNotFound()
    async def configuration(request):
        if request.method=='GET':return answer(runtime.storage.config())
        changes=await body(request)
        async with runtime.mutation:
            if runtime.running():raise BridgeError('stop_game_before_configuration')
            return answer(runtime.storage.update(changes))
    async def ini(request):
        value=await body(request)
        async with runtime.mutation:
            if runtime.running():raise BridgeError('stop_game_before_configuration')
            return answer(runtime.storage.import_ini(value['encoding'],value.get('data_relative','Data Files')))
    async def game(request):
        value=await body(request)
        if set(value)-{'op','args'} or value.get('op') not in operations:raise BridgeError('unknown_operation')
        args=value.get('args',{})
        if not isinstance(args,dict) or any(k.startswith('_') for k in args):raise BridgeError('invalid_arguments')
        return answer(await runtime.game(request.headers.get('X-Astra-Session'),value['op'],args))
    async def schema(request):return answer(commands)
    async def agent(request):
        action=request.match_info['action']
        if action=='connect':return answer(await runtime.acquire_agent((await body(request)).get('name','Gameplay agent')))
        if action=='disconnect':return answer(await runtime.release(request.headers.get('X-Astra-Session')))
        if action=='status':return answer(runtime.owner.public())
        raise web.HTTPNotFound()
    async def end_agent(request):return answer(await runtime.release(admin=True))
    async def record(request):
        if not runtime.running():raise BridgeError('game_not_running')
        action=request.match_info['action']
        if action not in {'start','stop','status'}:raise web.HTTPNotFound()
        result=await asyncio.to_thread(runtime.session.control.execute,'record_'+action,{})
        return answer(runtime.project(result))
    async def recordings(request):return answer(runtime.recordings())
    async def atlas(request):
        args={k:int(v) if k in {'page','limit'} else float(v) if k=='radius_m' else v
              for k,v in request.query.items() if k in {'space','query','page','limit','radius_m','level','route'}}
        return answer(await asyncio.to_thread(runtime.atlas,args))
    async def artifact(request):
        path=runtime.artifacts.get(request.match_info['id'])
        if not path or not path.is_file():raise web.HTTPNotFound()
        kind='recording' if path.is_relative_to(runtime.root/'recordings') else 'observation'
        return web.FileResponse(path,headers={'X-Content-Type-Options':'nosniff','Cache-Control':'private, no-cache',
            'X-Astra-Artifact-Kind':kind,'X-Astra-Artifact-Name':quote(path.name,safe='')})
    async def logs(request):
        name=request.query.get('name','daemon.log')
        files={p.name:p for p in (runtime.root/'logs').glob('*.log')}
        files['engine-private.log']=runtime.root/'runtime/engine-private.log'
        if name not in files: return answer({'names':sorted(files),'name':name,'text':''})
        path=files[name]
        if not path.exists():return answer({'names':sorted(files),'name':name,'text':''})
        with path.open('rb') as stream:
            stream.seek(max(0,path.stat().st_size-128000));text=stream.read().decode(errors='replace')
        return answer({'names':sorted(files),'name':name,'text':text})
    async def sessions(request):
        path=runtime.root/'sessions/events.jsonl'
        return answer([json.loads(line) for line in path.read_text().splitlines()[-200:]] if path.exists() else [])
    async def environment(request):return answer({**runtime.build,'graphics':runtime.graphics.info,'storage':runtime.storage.state})
    async def live(request):
        if request.method=='DELETE':return answer(await runtime.viewer(False))
        value=await body(request);return answer(await runtime.viewer(True,value.get('quality')))
    async def whep(request):
        if not runtime.live or not runtime.live.status()['running']:raise BridgeError('live_not_started')
        suffix=request.match_info.get('id','')
        if suffix:
            try:uuid.UUID(suffix)
            except ValueError:raise web.HTTPNotFound()
        url='http://127.0.0.1:18889/live/whep'+('/'+suffix if suffix else '')
        headers={k:v for k,v in request.headers.items() if k.lower() in {'content-type','if-match'}}
        async with ClientSession(timeout=ClientTimeout(total=15)) as client:
            async with client.request(request.method,url,data=await request.read(),headers=headers) as response:
                result_headers={k:v for k,v in response.headers.items() if k.lower() in {'content-type','etag','accept-patch'}}
                if 'Location' in response.headers:
                    result_headers['Location']='/v1/runtime/live/whep/'+response.headers['Location'].rstrip('/').split('/')[-1]
                return web.Response(status=response.status,body=await response.read(),headers=result_headers)
    async def events(request):
        socket=web.WebSocketResponse(heartbeat=15,max_msg_size=8192)
        await socket.prepare(request);sockets.add(socket);connection=uuid.uuid4().hex
        try:
            async for message in socket:
                if message.type!=WSMsgType.TEXT:continue
                try:
                    value=json.loads(message.data);kind=value.get('type')
                    if kind=='manual.acquire':result=await runtime.manual(connection,True)
                    elif kind=='manual.release':result=await runtime.manual(connection,False)
                    elif kind=='input':
                        if runtime.transition or runtime.owner.mode!='manual' or runtime.owner.token!=connection:
                            raise BridgeError('manual_input_not_owned')
                        runtime.input.event(value.get('event'));continue
                    else:raise BridgeError('invalid_event')
                    await socket.send_json({'type':'input.owner','data':result})
                except (BridgeError,ValueError,TypeError) as exc:
                    await socket.send_json({'type':'error','error':str(exc)})
        finally:
            sockets.discard(socket)
            await runtime.manual(connection,False)
        return socket
    async def broadcast():
        previous_frames=0;previous_rendered=0;previous_time=asyncio.get_running_loop().time()
        while True:
            status=runtime.project(runtime.status())
            now=asyncio.get_running_loop().time()
            status['capture_fps']=(status['frames']-previous_frames)/max(.001,now-previous_time)
            status['game_fps']=max(0,status['rendered_frames']-previous_rendered)/max(.001,now-previous_time)
            previous_rendered=status['rendered_frames']
            previous_frames,previous_time=status['frames'],now
            for socket in tuple(sockets):
                try:await asyncio.wait_for(socket.send_json({'type':'status','data':status}),.5)
                except Exception:sockets.discard(socket);await socket.close()
            await asyncio.sleep(.5)
    async def lifetime(app):
        tasks=[asyncio.create_task(runtime.tick()),asyncio.create_task(broadcast())]
        yield
        for task in tasks:task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):await task
        for socket in tuple(sockets):await socket.close()
        await runtime.close()
    app.cleanup_ctx.append(lifetime)
    app.add_routes([web.get('/health',health),web.get('/v1/runtime/status',status),web.get('/v1/runtime/gpus',gpus),
        web.post('/v1/runtime/engine/{action}',engine),web.get('/v1/runtime/config',configuration),
        web.patch('/v1/runtime/config',configuration),web.post('/v1/runtime/import-ini',ini),
        web.get('/v1/game/schema',schema),web.post('/v1/game/command',game),
        web.post('/v1/agent/{action}',agent),web.get('/v1/agent/status',agent),
        web.post('/v1/runtime/agent/end',end_agent),web.post('/v1/runtime/recording/{action}',record),
        web.get('/v1/runtime/recordings',recordings),web.get('/v1/runtime/atlas',atlas),
        web.get('/v1/artifacts/{id}',artifact),web.get('/v1/runtime/logs',logs),
        web.get('/v1/runtime/sessions',sessions),web.get('/v1/runtime/environment',environment),
        web.post('/v1/runtime/live',live),web.delete('/v1/runtime/live',live),
        web.post('/v1/runtime/live/whep',whep),web.patch('/v1/runtime/live/whep/{id}',whep),
        web.delete('/v1/runtime/live/whep/{id}',whep),web.get('/v1/events',events)])
    return app
