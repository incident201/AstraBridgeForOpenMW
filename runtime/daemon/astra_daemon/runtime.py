from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
import math
import copy
import logging
import threading
from logging.handlers import RotatingFileHandler

from astra_bridge.environment import identity
from astra_bridge.protocol import BridgeError, number
from astra_bridge.exploration import ExplorationAtlas
from astra_bridge.session import Session
from .graphics import Graphics
from .input import Input
from .live import Live
from .ownership import Ownership
from .storage import Storage
from .replay import Replay
from .profiles import Profiles


class Runtime:
    def __init__(self, installation: Path, storage: Path, game: Path):
        self.installation,self.base,self.game_root=installation,storage,game
        self.profiles=Profiles(storage,game,installation)
        self.root=self.profiles.path();self.recordings_root=self.profiles.recordings()
        self.recordings_root.mkdir(parents=True,exist_ok=True)
        self.storage=Storage(self.root,game,installation)
        self.graphics=Graphics(installation,self.root)
        self.owner=Ownership();self.session=None;self.input=None;self.live=None
        self.viewer_generation=0;self.termination=None
        self.transition=False;self.mutation=asyncio.Lock()
        self.starting=False;self.stopping=False;self.start_cancelled=threading.Event();self.start_log_offset=0
        self.artifacts={};self.last_error=None;self.started=time.time()
        self.replay=Replay(self.recordings_root)
        self.atlas_cache={'supported':False}
        self.log_handler=None;self.file_logging=False
        self.build=json.loads((installation/'runtime-manifest.json').read_text()) if (installation/'runtime-manifest.json').exists() else {}

    def running(self):
        session=self.session;process=session.process if session else None
        return bool(session and getattr(session,'ready',True) and process and process.poll() is None)

    def profile_logging(self,enabled=True):
        self.file_logging=enabled
        if self.log_handler:
            logging.getLogger().removeHandler(self.log_handler);self.log_handler.close();self.log_handler=None
        if enabled:
            self.root.joinpath('logs').mkdir(parents=True,exist_ok=True)
            self.log_handler=RotatingFileHandler(self.root/'logs/daemon.log',maxBytes=4*1024*1024,backupCount=3)
            logging.getLogger().addHandler(self.log_handler)

    def status(self):
        session=self.session
        frame=session.display.frame_stream if session else None
        media=session.display.media_stream if session else None
        def reading(stream,field,default=0):
            try:return getattr(stream,field) if stream else default
            except (ValueError,BufferError):return default  # A worker may just have closed its mmap.
        return {'profile':self.profiles.public(),'running':self.running(),'starting':self.starting,'stopping':self.stopping,'session_end':self.termination,'owner':self.owner.public(),'transitioning':self.transition,
                'active_action':session.control.status() if session else None,
                'session':session.session_id if session else None,
                'clocks':session.timeline.clocks() if session else None,
                'timeline':session.timeline.recent() if session else [],
                'recording':session.recorder.status() if session and session.recorder else None,
                'viewer':self.live.status() if self.live else {'running':False},
                'graphics':{k:v for k,v in self.graphics.info.items() if k!='probe'},
                'frames':reading(frame,'sequence'),'media_samples':reading(media,'samples'),
                'rendered_frames':reading(frame,'rendered_frames'),
                'world_active':reading(media,'active',False),'uptime_seconds':time.time()-self.started,
                'environment':self.build,'error':self.last_error}

    def _history(self, event, **fields):
        with (self.root/'sessions/events.jsonl').open('a') as stream:
            stream.write(json.dumps({'time':time.time(),'event':event,**fields},ensure_ascii=False)+'\n')

    def _start_engine(self, gpu=None):
        cfg=self.storage.prepare_profile()
        display=self.graphics.start(cfg['graphics']=='software',gpu or cfg['graphics_gpu'])
        if os.environ.get('ASTRA_GPU_BACKEND')=='wsl':os.environ['DISPLAY']=display
        session=Session(self.installation/'runtime',self.installation,display=display,sound=cfg['sound'],storage=self.root,recordings_dir=self.recordings_root)
        session.desktop_profile=self.profiles.public()
        session.display.env.update(self.graphics.environment)
        self.session=session
        if self.start_cancelled.is_set():raise BridgeError('startup_cancelled',message='Game startup was cancelled.')
        session.start()
        if self.start_cancelled.is_set():raise BridgeError('startup_cancelled',message='Game startup was cancelled.')
        self.input=Input(display,self.graphics.environment)
        self._history('engine_started',session=session.session_id)
        self.last_error=None

    async def start_engine(self, gpu=None, profile=None):
        if gpu is not None and (not isinstance(gpu,str) or gpu not in ('auto','nvidia') and not gpu.startswith('pci:')):
            raise BridgeError('invalid_graphics_gpu')
        async with self.mutation:
            if profile is not None and profile!=self.profiles.data['active']:raise BridgeError('profile_mismatch',profile=self.profiles.public())
            if self.running():
                if gpu is not None and gpu!=self.graphics.info.get('requested_gpu'):
                    raise BridgeError('restart_required_to_change_gpu')
                return self.status()
            if self.session:await asyncio.to_thread(self._stop_engine)
            self.starting=True;self.start_cancelled.clear();self.last_error=None;self.termination=None
            log=self.root/'runtime/engine-private.log'
            self.start_log_offset=log.stat().st_size if log.exists() else 0
            try:await asyncio.to_thread(self._start_engine,gpu)
            except Exception as exc:
                await asyncio.to_thread(self._stop_engine)
                if self.start_cancelled.is_set():
                    raise BridgeError('startup_cancelled',message='Game startup was cancelled.') from exc
                if isinstance(exc,BridgeError) and exc.details.get('message'):
                    self.last_error=exc.details['message'];raise
                log=self.root/'runtime/engine-private.log'
                tail=''
                if log.exists():
                    with log.open('rb') as stream:
                        stream.seek(max(self.start_log_offset,log.stat().st_size-16000));tail=stream.read().decode(errors='replace')
                fatal=next((line.split('Fatal error:',1)[1].strip() for line in reversed(tail.splitlines()) if 'Fatal error:' in line),None)
                self.last_error=f'OpenMW could not finish starting: {fatal or str(exc)}. See Diagnostics → engine-private.log.'
                raise BridgeError('game_start_failed',message=self.last_error) from exc
            finally:self.starting=False
        return self.status()

    def _stop_engine(self):
        if self.live:self.live.close();self.live=None
        if self.input:self.input.close();self.input=None
        if self.session:
            session=self.session
            session.timeline.agent(False)
            session.control.interrupt()
            with session.control.owner,session.lock:
                session.close()
                for component in (session.knowledge,session.atlas,session.control.receipts):
                    database=getattr(component,'db',None)
                    if database:database.close()
            self._history('engine_stopped',session=session.session_id)
            self.session=None
        self.owner.release()

    async def stop_engine(self, reason=None):
        if reason:
            self.termination={'reason':reason,'at':time.time(),'session':self.session.session_id if self.session else None}
            if self.session:
                self.session.termination=self.termination
                self.session.timeline.emit('session_end',**self.termination)
            self._history('session_end',**self.termination)
            if self.session:await asyncio.to_thread(self.session.control.interrupt)
        self.stopping=True
        try:
            # A startup worker owns mutation while loading. Cancel it before waiting
            # for that lock; a hung logo or failed handshake cannot block Stop.
            if self.starting:
                self.start_cancelled.set()
                if self.session:await asyncio.to_thread(self.session.abort_startup)
            async with self.mutation:
                self.transition=True
                try:await asyncio.to_thread(self._stop_engine)
                finally:self.transition=False
        finally:self.stopping=False
        return self.status()

    def _mode(self, mode):
        if self.input:self.input.release()
        if self.running():
            s=self.session;s.control.interrupt()
            with s.control.owner,s.lock:
                s.control.cancelled.clear()
                s.command('stop',_runtime_mode=mode)
                s.display.media_stream.ui(mode=='manual')
                if s.recorder:s.recorder.set_active('manual',mode=='manual')

    async def acquire_agent(self, name, profile=None):
        async with self.mutation:
            if profile is not None and profile!=self.profiles.data['active']:raise BridgeError('profile_mismatch',profile=self.profiles.public())
            if not self.running():raise BridgeError('game_not_running')
            if self.owner.mode=='agent':raise BridgeError('agent_already_connected')
            self.transition=True
            try:
                await asyncio.to_thread(self._mode,'agent')
                hint=await asyncio.to_thread(self.session.working_memory_hint)
                result={**self.owner.acquire_agent(name),'profile':self.profiles.public(),'working_memory':hint}
                self.session.timeline.agent(True)
                self._history('agent_connected',name=name)
                return result
            finally:self.transition=False

    async def release(self, token=None, admin=False):
        async with self.mutation:
            if not admin:self.owner.verify_agent(token)
            self.transition=True
            try:
                await asyncio.to_thread(self._mode,'idle')
                if self.session:self.session.timeline.agent(False)
                self._history('owner_disconnected',mode=self.owner.mode,by_user=admin)
                self.owner.release()
            finally:self.transition=False
        return self.owner.public()

    async def manual(self, token, enable):
        async with self.mutation:
            if enable:
                if not self.running():raise BridgeError('game_not_running')
                self.owner.acquire_manual(token)
            elif self.owner.mode!='manual' or self.owner.token!=token:return self.owner.public()
            self.transition=True
            try:await asyncio.to_thread(self._mode,'manual' if enable else 'idle')
            except Exception:
                self.owner.release();raise
            finally:self.transition=False
            if not enable:self.owner.release()
        return self.owner.public()

    async def game(self, token, op, args):
        def stopped(end, **details):
            return BridgeError('user_requested_stop',message='The user stopped this session. Do not reconnect or restart without a new user request.',
                               session_end=end,retryable=False,**details)
        if self.termination:raise stopped(self.termination)
        if self.transition:raise BridgeError('input_transitioning')
        self.owner.verify_agent(token)
        if not self.running():raise BridgeError('game_not_running')
        session=self.session
        try:result=await asyncio.to_thread(session.control.execute,op,args)
        except Exception as exc:
            if getattr(session,'termination',None):
                raise stopped(session.termination,action_error=exc.response() if isinstance(exc,BridgeError) else str(exc)) from exc
            raise
        if getattr(session,'termination',None):raise stopped(session.termination,action_result=self.project(result))
        return self.project(result)

    async def viewer(self, enabled, quality=None):
        if enabled and (self.stopping or self.termination):raise BridgeError('session_stopping')
        self.viewer_generation+=1;generation=self.viewer_generation
        if not enabled and self.live is None:return {'running':False}
        async with self.mutation:
            if generation!=self.viewer_generation:return self.live.status() if self.live else {'running':False}
            if self.live and (not enabled or quality and self.live.quality!=quality or not self.live.status()['running']):
                await asyncio.to_thread(self.live.close);self.live=None
            if enabled and not self.live:
                if not self.running():raise BridgeError('game_not_running')
                live=Live(self.session,self.installation,quality or self.storage.config()['viewer_quality'])
                try:await asyncio.to_thread(live.start)
                except Exception:
                    await asyncio.to_thread(live.close);raise
                if generation!=self.viewer_generation:
                    await asyncio.to_thread(live.close);return {'running':False}
                self.live=live
        return self.live.status() if self.live else {'running':False}

    async def profile_operation(self,operation,args):
        async with self.mutation:
            if self.running():raise BridgeError('stop_game_before_managing_profiles')
            if operation not in {'create','rename','switch','delete','duplicate'}:raise BridgeError('unknown_profile_operation')
            allowed={'name'} if operation=='create' else {'id','name'} if operation in {'rename','duplicate'} else {'id'}
            if set(args)-allowed or operation!='create' and not isinstance(args.get('id'),str):raise BridgeError('invalid_arguments')
            key=args.get('id');old=self.profiles.data['active']
            if key:self.profiles.get(key)
            if operation in {'switch','delete','duplicate'}:
                await asyncio.to_thread(self._stop_engine)
                await asyncio.to_thread(self.graphics.close)
            logging_enabled=self.file_logging
            if operation=='delete':self.profile_logging(False)
            try:
                if operation=='create':result=await asyncio.to_thread(self.profiles.create,args.get('name'),self.storage.config())
                elif operation=='duplicate':result=await asyncio.to_thread(self.profiles.duplicate,key,args.get('name'))
                elif operation=='rename':result=self.profiles.rename(key,args.get('name'))
                elif operation=='switch':result=self.profiles.select(key)
                else:result=await asyncio.to_thread(self.profiles.delete,key,self.storage.config())
            finally:
                if old!=self.profiles.data['active']:
                    self.root=self.profiles.path();self.recordings_root=self.profiles.recordings()
                    self.recordings_root.mkdir(parents=True,exist_ok=True)
                    self.storage=Storage(self.root,self.game_root,self.installation)
                    self.graphics=Graphics(self.installation,self.root)
                    self.replay=Replay(self.recordings_root);self.artifacts={};self.atlas_cache={'supported':False}
                    self.last_error=None
                if logging_enabled:self.profile_logging()
            return {'result':result,**self.profiles.catalog()}

    def project(self, value):
        if isinstance(value,dict):return {k:self.project(v) for k,v in value.items()}
        if isinstance(value,list):return [self.project(v) for v in value]
        if isinstance(value,str) and value.startswith(str(self.base)+'/'):
            path=Path(value)
            resolved=path.resolve()
            if path.is_file() and (resolved.parent==self.recordings_root.resolve() or resolved.is_relative_to((self.root/'runtime/screenshots').resolve())):
                key=hashlib.sha256((self.profiles.data['active']+'/'+str(path.relative_to(self.base))).encode()).hexdigest()[:32]
                self.artifacts[key]=path;return '/v1/artifacts/'+key
            return None
        return value

    def replay_info(self, key=None):
        session=self.session;recorder=session.recorder if session else None
        active=recorder.path if recorder and not recorder.closing else None
        if not active and session and session.last_recording and session.last_recording.get('path'):
            self.replay.last=self.replay.identify(session.last_recording['path'])
        info=self.replay.info(active,key)
        info['profile_subdirectory']=self.profiles.public()['recordings_subdirectory']
        if info['id'] and info['kind']=='file':info['url']=self.project(str(self.replay.paths[info['id']]))
        return info

    def recordings(self):
        rows=[]
        for path in sorted(self.recordings_root.glob('*.mp4'),key=lambda p:p.stat().st_mtime,reverse=True):
            if path.name.endswith('.finalizing.mp4'):continue
            row={'id':path.stem,'name':path.name,'bytes':path.stat().st_size,'created':path.stat().st_mtime,
                 'video':self.project(str(path))}
            for suffix,field in (('.json','metadata'),('.encoder.json','encoder'),('.ffmpeg.log','diagnostics')):
                sidecar=path.with_suffix(suffix)
                if sidecar.exists():row[field]=self.project(str(sidecar))
            rows.append(row)
        return rows

    def atlas(self, args):
        # Desktop queries project retained travel data. They must not run the
        # Game API's observe/pause action while a human or an agent is moving.
        if self.session and self.session.control.status():return self.atlas_cache
        import contextlib
        offline=self.session is None
        atlas=ExplorationAtlas(self.root/'atlas/exploration-memory.json') if offline else self.session.atlas
        lock=contextlib.nullcontext() if offline else self.session.lock
        with lock:
            active=atlas.segment
            try:
                spaces=atlas.catalog()
                target=args.get('space') or active or (spaces[-1]['ref'] if spaces else None)
                if target and not atlas.graph_for(target):raise BridgeError('unknown_map_space')
                atlas.segment=target
                if args.get('route'):
                    result=copy.deepcopy(atlas.route_to(args['route']))
                    if not result:raise BridgeError('recorded_route_unavailable')
                    for step in result['steps']:step.get('door',{}).pop('anchor',None)
                    return result
                page=args.get('page',0);limit=args.get('limit',100)
                if type(page) is not int or type(limit) is not int:raise BridgeError('invalid_arguments')
                number(page,0,1_000_000);number(limit,1,1000)
                if 'query' in args:result=atlas.search(args['query'],target,page,limit,args.get('level'))
                else:
                    path=self.root/'runtime/screenshots/atlas-desktop.svg'
                    result=atlas.present(path,number(args.get('radius_m',35),.1,100_000),
                        archived=offline or target!=active,page=page,limit=limit,level=args.get('level'),map_only=True)
                    result['spaces']=spaces;result['historical']=offline or target!=active
                self.atlas_cache=self.project(result)
                return self.atlas_cache
            finally:
                atlas.segment=active
                if offline:atlas.db.close()

    async def tick(self):
        while True:
            if self.owner.mode=='manual' and self.running() and not self.transition:
                try:
                    session=self.session
                    def observe():
                        with session.lock:
                            if self.session is session and self.running() and self.owner.mode=='manual' and not self.transition:
                                return session.observe(capture=False,passive=True)
                    await asyncio.to_thread(observe)
                except Exception as exc:self.last_error=str(exc)
            elif not self.stopping and self.owner.mode!='idle' and not self.running():
                if self.session:self.session.timeline.agent(False)
                self.owner.release();self.last_error='game_exited'
            await asyncio.sleep(1)

    async def close(self):
        await self.stop_engine()
        await asyncio.to_thread(self.graphics.close)
        self.profile_logging(False)
