from __future__ import annotations

from contextlib import contextmanager
import configparser
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import uuid

from .display import Display
from .protocol import BridgeError, ERRORS, atomic_json, check_result, validate, number, LogDecoder, action_timeout
from .recording import Recorder
from .environment import engine_path, identity
from .frame_stream import FrameStream
from .media_stream import MediaStream
from .memory import SpatialMemory
from .terrain_map import render_terrain
from .feedback import feedback
from .exploration import ExplorationAtlas
from .control import Control
from .observations import prune_screenshots, present_response
from . import workflows
from . import information
from .knowledge import Knowledge
from .autosave import Autosave
from .tribunal import prepare_tribunal_delay


def observation_changes(before,after):
    if not before or before.get('state')!='running' or after.get('state')!='running':return {}
    changes={}
    old,new=before.get('stats',{}).get('gold'),after.get('stats',{}).get('gold')
    if type(old) is int and type(new) is int and old!=new:changes['gold_change']=new-old
    old,new=before.get('location'),after.get('location')
    if old and new and old!=new:changes.update(location_changed=True,from_location=old,to_location=new)
    if before.get('ui_mode')!=after.get('ui_mode'):
        changes.update(ui_from=before.get('ui_mode'),ui_to=after.get('ui_mode'))
    return changes


class Session:
    def __init__(self, root: Path, installation: Path, *, headless=False, display=None, sound=True, recordings_dir=None, storage=None):
        self.root, self.installation = root, installation
        self.storage = Path(storage) if storage else None
        self.runtime = (self.storage or root) / "runtime"
        self.runtime.mkdir(mode=0o700, exist_ok=True)
        local = self.storage / 'configuration.json' if self.storage else root / 'local-settings.json'
        local_settings = json.loads(local.read_text()) if local.exists() else {}
        from .encoding import settings as recording_settings
        self.recording_settings = recording_settings(local_settings)
        self.recordings_dir = Path(recordings_dir or os.environ.get('ASTRA_RECORDINGS_DIR') or
                                   local_settings.get('recordings_dir') or (self.storage or self.runtime) / 'recordings')
        self.engine_binary = local_settings.get('engine_binary')
        self.engine_libraries = local_settings.get('engine_libraries')
        self.production = os.environ.get('ASTRA_MODE') == 'production'
        if self.production and (self.engine_binary or self.engine_libraries):
            raise BridgeError('development_override_in_production')
        self.delay_tribunal = local_settings.get('delay_tribunal', True)
        self.screenshot_keep = local_settings.get('screenshot_keep',128)
        if type(self.screenshot_keep) is not int or self.screenshot_keep < 8:
            raise BridgeError('invalid_screenshot_keep')
        knowledge_dir = self.storage / 'atlas' if self.storage else self.runtime
        knowledge_dir.mkdir(exist_ok=True)
        self.memory = SpatialMemory(knowledge_dir / 'spatial-memory.json')
        self.atlas = ExplorationAtlas(knowledge_dir / 'exploration-memory.json')
        self.profile = (self.storage or self.runtime) / "profile"
        self.profile.mkdir(exist_ok=True)
        self.inbox = self.runtime / "data/astrabridge-runtime/inbox.json"
        self.inbox.parent.mkdir(parents=True, exist_ok=True)
        self.display = Display(root, self.runtime, display, headless)
        self.sound = sound
        self.display.sound = sound
        self.process = None
        self.condition = threading.Condition()
        self.responses = {}
        self.travel_updates = []
        self.session_id = ""
        self.command_id = 0
        self.observation_id = 0
        self.latest_observation = None
        self.reader = None
        self.uncertain = False
        self.lock = threading.RLock()
        self.recorder = None
        self.last_recording = None
        self.save_refs = {}
        self.knowledge=Knowledge(knowledge_dir/'agent-memory.sqlite3')
        self.autosave=Autosave(self.profile/'autosave.json')
        self.sequence_guard=None
        self.control = Control(self)

    def prepare(self):
        config = self.storage / 'profile/base' if getattr(self, 'storage', None) else self.installation / 'config'
        cfg = (config / "openmw.cfg").read_text()
        cfg += f'\ndata="{self.root / "mod"}"\ndata="{self.runtime / "data"}"\ncontent=AstraBridge.omwscripts\n'
        cfg = prepare_tribunal_delay(cfg, self.runtime / 'data',
                                     base_dir=self.profile,
                                     enabled=getattr(self, 'delay_tribunal', True),
                                     local_data=self.runtime / 'local-data')
        (self.profile / "openmw.cfg").write_text(cfg)
        settings = (config / "settings.cfg").read_text()
        border='false' if self.display.headless else 'true'
        settings += f"\n[Video]\nfullscreen = false\nwindow border = {border}\nresolution x = 1920\nresolution y = 1080\nvsync = false\nframerate limit = 60\n[GUI]\nsubtitles = true\n"
        # Write initial settings only once; later UI changes persist in the isolated profile.
        if not (self.profile / "settings.cfg").exists():
            (self.profile / "settings.cfg").write_text(settings)
        # Async physics commits the previous frame only on the next simulation
        # step. That makes an already-paused pose drift when a new command starts.
        # Keep input, collision results and the pause boundary in the same frame.
        settings_path = self.profile / 'settings.cfg'
        profile_settings = configparser.ConfigParser(interpolation=None, strict=False)
        profile_settings.read(settings_path)
        settings_changed = False
        # Game/video are 1080p; the public screenshot coordinate space is 720p.
        if not profile_settings.has_section('Video'): profile_settings.add_section('Video')
        for key,value in {'resolution x':'1920','resolution y':'1080'}.items():
            if profile_settings.get('Video',key,fallback=None)!=value:
                profile_settings.set('Video',key,value);settings_changed=True
        if profile_settings.get('Physics', 'async num threads', fallback=None) != '0':
            if not profile_settings.has_section('Physics'): profile_settings.add_section('Physics')
            profile_settings.set('Physics', 'async num threads', '0')
            settings_changed = True
        # Bundled YAIAF uses OpenMW's per-animation sources, without an ESP or
        # replacement base skeleton. Apply to existing isolated profiles as well.
        if (self.root / 'mod/Animations/xbase_anim/_xYAIAF.kf').is_file():
            if profile_settings.get('Game', 'use additional anim sources', fallback=None) != 'true':
                if not profile_settings.has_section('Game'): profile_settings.add_section('Game')
                profile_settings.set('Game', 'use additional anim sources', 'true')
                settings_changed = True
        if settings_changed:
            with settings_path.open('w') as output: profile_settings.write(output)
        for path in ("userdata", "cache", "screenshots", "local-data"):
            (self.runtime / path).mkdir(exist_ok=True)
        if getattr(self, 'storage', None):
            saves = self.storage / 'saves'
            saves.mkdir(exist_ok=True)
            link = self.runtime / 'userdata/saves'
            if not link.exists(): link.symlink_to(saves, target_is_directory=True)
        if hasattr(self,'memory') and hasattr(self,'atlas'):
            self.memory.attach_atlas(self.atlas)
            prune_screenshots(self.runtime/'screenshots',self.memory,self.screenshot_keep)
            self.atlas.import_transitions(self.runtime/'actions.jsonl')

    def start(self):
        self.prepare()
        self.display.start()
        return self.launch()

    def launch(self):
        self.session_id = uuid.uuid4().hex
        self.save_refs = {}
        self.atlas.reset_runtime()
        self.command_id, self.responses, self.latest_observation = 0, {}, None
        self.uncertain = False
        atomic_json(self.inbox, {"version": 1, "session": self.session_id, "id": 0, "op": "ping", "args": {}})
        atomic_json(self.inbox.with_name('input.json'), {})
        atomic_json(self.inbox.with_name('cancel.json'), {})
        try:
            packaged = engine_path(self.installation)
        except ValueError as exc:
            raise BridgeError("openmw_binary_missing") from exc
        environment = identity(self.root)
        atomic_json(self.runtime / "environment.json", environment)
        atomic_json(self.runtime / ("environment-" + self.session_id + ".json"), environment)
        binary = Path(self.engine_binary) if self.engine_binary else packaged
        if self.display.frame_stream: self.display.frame_stream.close()
        self.display.frame_stream = FrameStream(self.runtime / 'engine-frames.bin')
        env = self.display.env.copy()
        env['ASTRA_FRAME_STREAM'] = str(self.display.frame_stream.path)
        if self.display.media_stream: self.display.media_stream.close()
        self.display.media_stream = MediaStream(self.runtime/'engine-media.bin')
        env['ASTRA_MEDIA_STREAM'] = str(self.display.media_stream.path)
        libraries=self.engine_libraries or str(packaged.parent/'lib')
        env['LD_LIBRARY_PATH']=libraries+(':'+env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
        env["XDG_CACHE_HOME"] = str(self.runtime / "cache")
        env["SDL_VIDEODRIVER"] = "x11"
        plugins=packaged.parent/'lib/osgPlugins-3.6.5'
        if plugins.is_dir():env['OSG_LIBRARY_PATH']=str(plugins)
        # Direct binary: own PID/window and process group, no wrapper process to orphan.
        args = [str(binary), "--replace", "config", "--config", str(self.profile),
                "--user-data", str(self.runtime / "userdata"), "--data-local", str(self.runtime / "local-data"),
                "--resources", str(packaged.parent / "resources"), "--no-sound", "0" if self.sound else "1"]
        if self.production: args.append('--disable-console')
        self.process = subprocess.Popen(args, cwd=packaged.parent, env=env, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, start_new_session=True)
        self.reader = threading.Thread(target=self._read_output, args=(self.process, self.session_id), daemon=True)
        self.reader.start()
        # VFS inbox exists before startup; first handshake may wait for asset loading.
        result = self.command("ping", {}, timeout=60)
        deadline = time.monotonic() + 10
        while True:
            try:
                self.display.focus(self.process.pid)
                break
            except BridgeError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.1)
        return result

    def _read_output(self, process, session_id):
        decoder=LogDecoder()
        with open(self.runtime / "engine-private.log", "ab") as log:
            while line := process.stdout.readline():
                log.write(line)
                log.flush()
                if len(line) > 2_000_000:
                    continue
                try:
                    message = decoder.feed(line)
                    if message is None:continue
                    if message.get("session") != session_id or message.get("version") != 1:
                        continue
                    if message.get('event') == 'progress':
                        result=message.get('result', {})
                        with self.condition:
                            self.travel_updates.extend(result.pop('_atlas_travel', []))
                            self.condition.notify_all()
                        self.control.progress(check_result(result))
                        continue
                    if message.get("event") in {"simulation","camera_motion"} and type(message.get("active")) is bool:
                        if self.recorder:
                            self.recorder.set_active(message['event'], message["active"])
                        continue
                    if message.get('event') == 'native_input':
                        if message.get('name') == 'Activate' and message.get('id') == self.command_id:
                            ok = True
                            try:
                                self.display.native_activate(self.profile)
                            except Exception:
                                ok = False
                            atomic_json(self.inbox.with_name('input.json'), {'session':session_id,'id':message['id'],'ok':ok})
                        continue
                    if message.get("status") not in {"completed", "rejected"}:
                        continue
                    with self.condition:
                        self.responses[message["id"]] = message
                        self.condition.notify_all()
                except (ValueError, TypeError, KeyError, BridgeError):
                    continue
        with self.condition:
            self.condition.notify_all()

    def command(self, op, args=None, *, timeout=25, _atlas_offset=None, _atlas_route=None, _save_ref=None,
                _runtime_mode=None, _passive=False):
        args = args or {}
        validate(op, args)
        if _runtime_mode is not None:
            if op != 'stop' or _runtime_mode not in {'idle','manual','agent'}: raise BridgeError('invalid_runtime_mode')
            args={**args,'_runtime_mode':_runtime_mode}
        if _passive:
            if op != 'observe': raise BridgeError('invalid_passive_query')
            args={**args,'_passive':True}
        if getattr(self, 'control', None) and self.control.cancelled.is_set() and op not in {'stop','observe','ping','quit','inspect','ui'}:
            raise BridgeError('cancelled')
        if op in {'pick','walk'} and 'x' in args and 'y' in args:
            x,y=self.display.native_point(args['x'],args['y'])
            args={**args,'x':x,'y':y}
            if 'radius' in args:
                args['radius']=args['radius']*self.display.width/self.display.observation_size()[0]
        timeout = action_timeout(op, args, max(timeout, 70))
        if getattr(self,'sequence_guard',None) and op not in {'observe','inspect','ui','mark','stop'}:
            args={**args,'_guard':self.sequence_guard}
        if _save_ref is not None:
            assert op=='save'
            args={**args,'_replace_ref':_save_ref}
        if _atlas_offset is not None:
            assert op == 'mark'
            args = {**args, '_atlas_offset': _atlas_offset}
        if _atlas_route is not None:
            assert op == 'mark' and _atlas_offset is not None
            args = {**args, '_atlas_route': _atlas_route}
        # Private transport cursor; the public observe command has no extra fields.
        # Every observation request (including internal UI checks) ingests its delta.
        if op == 'observe' and self.atlas.segment:
            args = {**args, '_trail_segment': self.atlas.visit, '_trail_after': self.atlas.sequence}
        if not self.process or self.process.poll() is not None:
            raise BridgeError("game_not_running")
        if self.uncertain and op not in {"stop", "ping", "quit"}:
            raise BridgeError("previous_result_unknown_stop_or_restart")
        self.command_id += 1
        cmd_id = self.command_id
        message = {"version": 1, "session": self.session_id, "id": cmd_id, "op": op, "args": args}
        atomic_json(self.inbox, message)
        deadline = time.monotonic() + timeout
        with self.condition:
            while cmd_id not in self.responses:
                self._drain_travel()
                if self.process.poll() is not None:
                    raise BridgeError("game_exited")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.uncertain = True
                    # Never retry consumables or other mutations automatically.
                    raise BridgeError("result_unknown_stop_or_restart")
                self.condition.wait(min(.2, remaining))
            response = self.responses.pop(cmd_id)
            self._drain_travel()
        if response.get("status") == "rejected":
            error = response.get("error")
            raise BridgeError(error if error in ERRORS else "operation_failed")
        if op == "stop":
            self.uncertain = False
        raw = response.get("result", {})
        inventory=raw.pop('_inventory_counts',None)
        if inventory is not None and (not isinstance(inventory,dict) or any(not isinstance(k,str) or type(v) is not int or v<0 for k,v in inventory.items())):raise BridgeError('invalid_bridge_response')
        for travel in raw.pop('_atlas_travel',[]):self._ingest_travel(travel)
        # This metadata never crosses the public projection boundary.
        frame = raw.pop('_atlas_frame', None) if op == 'observe' else None
        if frame is not None:
            self._validate_frame(frame)
        # Use the same durable profile as the atlas, including on lifecycle changes.
        if op == 'load': self.atlas.restore(self.save_refs.get(args.get('ref')))
        if op == 'new_game': self.atlas.new_game()
        self.knowledge.recognize(raw, self.atlas.profile)
        result = self.display.public_coordinates(check_result(raw))
        if inventory is not None:result['inventory_summary']=inventory
        if op in {'load','new_game'}:
            self.autosave.clock=None
        self.knowledge.ingest(op,result)
        if 'saves' in result: self.save_refs = {s['ref']: s for s in result['saves']}
        if op == 'observe': self.atlas.ingest(result, frame)
        if op == 'mark' and result.get('ref'): self.atlas.note_marker(result['ref'])
        return result

    @staticmethod
    def _validate_frame(frame):
        if (type(frame) is not dict or set(frame)!={'space','origin'}
            or not isinstance(frame['space'],str) or len(frame['space'])>1024
            or not isinstance(frame['origin'],list) or len(frame['origin'])!=3):
            raise BridgeError('invalid_bridge_response')
        for value in frame['origin']:number(value,-1e9,1e9)

    def _ingest_travel(self,travel):
        self._validate_frame(travel['frame'])
        observation=check_result({'trajectory':travel['trajectory'],'location':travel['location']})
        self.atlas.ingest(observation,travel['frame'])

    def _drain_travel(self):
        # Called by the command owner while holding condition; the reader only
        # queues deltas, so SQLite writes never race observations/route planning.
        for travel in getattr(self,'travel_updates',[]):self._ingest_travel(travel)
        self.travel_updates=[]

    def observe(self, *, capture=True, maps=False, passive=False):
        capture = capture and not getattr(self,'batch_depth',0)
        result = self.command("observe", _passive=passive)
        if result.get('ui',{}).get('blocked'):raise BridgeError('non_gameplay_ui')
        # Lua confirms pause and settles UI. Native capture waits for fresh
        # completed frames; legacy X11 fallback remains explicitly best-effort.
        time.sleep(.02)
        self.observation_id += 1
        path = self.runtime / "screenshots" / f"{self.session_id[:8]}-{self.observation_id:06}.png"
        result['observation'] = self.observation_id
        if capture:
            size = self.display.capture(path)
            result.update({"screenshot": str(path), "screen": size,
                       "capture_sync": "render_complete" if self.display.frame_stream.supported else "paused_best_effort",
                       "capture_backend":self.display.frame_stream.backend if self.display.frame_stream.supported else "xcomposite_window"})
        if maps and result.get('terrain',{}).get('supported'):
            map_path=path.with_suffix('.svg')
            render_terrain(result,map_path)
            result['local_map']=str(map_path)
        self.memory.observe_location(result)
        node = self.atlas.annotate(result)
        if not passive and node and result.get('terrain', {}).get('supported') and result.get('body', {}).get('on_ground') and not result.get('body', {}).get('swimming') and not result.get('body',{}).get('dead'):
            try:
                offset = [a-b for a,b in zip(node['p'], self.atlas.current()['pose'])]
                node['motor_ref'] = self.command('mark', _atlas_offset=offset)['ref']
                self.atlas.persist()
            except BridgeError as exc:
                node['marker_unavailable'] = str(exc)
        if result.get('state')=='running' and not result.get('body',{}).get('dead'):
            result['exploration'] = self.atlas.present(path.with_name(path.stem+'-atlas.svg') if maps else None) if maps or getattr(self,'full_observations',False) else self.atlas.summary()
        else:result['exploration']={'supported':False,'reason':'no_player'}
        result.pop('trajectory', None)  # transport samples stay in the controller; give the agent the map and named nodes
        self.autosave.observe(result)
        previous=self.latest_observation
        if previous and previous.get('state')=='running' and result.get('state')=='running':
            events=[]
            old_effects={e.get('name'):e for e in previous.get('effects',[])}
            new_effects={e.get('name'):e for e in result.get('effects',[])}
            for name in old_effects.keys()-new_effects.keys():events.append({'kind':'effect_ended','name':name})
            for name in new_effects.keys()-old_effects.keys():events.append({'kind':'effect_started','name':name})
            old_count=previous.get('journal_count');new_count=result.get('journal_count')
            if old_count is not None and new_count is not None and old_count!=new_count:events.append({'kind':'journal_changed','added':new_count-old_count,'details':'inspect journal'})
            old_items=previous.get('inventory_summary');new_items=result.get('inventory_summary')
            if old_items is not None and new_items is not None:
                for name in old_items.keys()|new_items.keys():
                    delta=new_items.get(name,0)-old_items.get(name,0)
                    if delta:events.append({'kind':'inventory_changed','name':name,'count_change':delta})
            if events:result['events']=[self.knowledge.event(e) for e in events]
        self.latest_observation = result
        if capture:
            prune_screenshots(self.runtime/'screenshots',self.memory,getattr(self,'screenshot_keep',128))
        return result

    def _check_ui(self, args):
        previous = self.latest_observation
        if not previous or args.get("observation") != previous["observation"]:
            raise BridgeError("stale_observation")
        current = self.command("observe")
        # Native tutorial message boxes can report Gameplay in Lua despite being
        # visible and interactive. A current screenshot is the authority for clicks.
        if current["ui_mode"] != previous["ui_mode"]:
            raise BridgeError("ui_changed_or_closed")
        self.display.focus(self.process.pid)

    @contextmanager
    def record_ui(self):
        recorder = self.recorder
        media = getattr(self.display,'media_stream',None)
        if media: media.ui(True)
        if recorder:
            recorder.set_active('ui', True)
        try:
            yield
        finally:
            if media: media.ui(False)
            if recorder:
                recorder.set_active('ui', False)

    def stop_recording(self):
        if self.recorder:
            self.last_recording = self.recorder.stop()
            self.recorder = None
        return self.last_recording or {'recording': False}

    def scan(self, pitch=0):
        current=self.observe()
        if current.get('state')!='running':raise BridgeError('no_player')
        if current.get('ui_mode')!='Gameplay' or current.get('ui',{}).get('modal'):raise BridgeError('ui_open')
        if current.get('target_lock',{}).get('status') not in {None,'unlocked','down'}:
            raise BridgeError('target_locked_unlock_first')
        heading=current['orientation']['heading_deg']
        elapsed=0.
        if abs(current['orientation'].get('pitch_deg',0)-pitch)>.5:
            result=self.call('look',{'pitch_deg':pitch})
            current=result['observation'];elapsed+=result['action'].get('elapsed',0)
            if result['action'].get('reason')!='duration' or current.get('ui_mode')!='Gameplay' or current.get('ui',{}).get('modal'):
                return {'views':[],'final':current,'completed':False,
                        'reason':'ui_input_required' if current.get('ui',{}).get('modal') else result['action'].get('reason','interrupted'),'elapsed':elapsed}
        views=[{'relative_yaw':0,'observation':current}]
        for offset in (90,180,270):
            delta=(heading+offset-current['orientation']['heading_deg']+180)%360-180
            # Rotate the actor with ordinary controls; no independent camera pose.
            result=self.call('act',{'yaw':delta,'seconds':.02})
            current=result['observation'];elapsed+=result['action'].get('elapsed',0)
            if result['action'].get('reason')!='duration' or current.get('ui_mode')!='Gameplay' or current.get('ui',{}).get('modal'):
                return {'views':views,'final':current,'completed':False,
                        'reason':'ui_input_required' if current.get('ui',{}).get('modal') else result['action'].get('reason','interrupted'),'elapsed':elapsed}
            views.append({'relative_yaw':offset,'observation':current})
        return {'views':views,'final':current,'completed':True,'reason':'completed','elapsed':elapsed}

    def call(self, op, args=None):
        args = args or {}
        if type(args) is not dict:
            raise BridgeError("invalid_arguments")
        with self.lock:
            started = time.monotonic()
            if op=='details':return information.details(self,args)
            if op=='knowledge':return self.knowledge.call(args, self.atlas.profile)
            if op=='autosave':return self.autosave.configure(args)
            if op=='ui':return information.query_ui(self,args)
            if op=='inspect' and args.get('view') in {'journal','conversations'} and ('query' in args or 'limit' in args):return information.inspect_text(self,args)
            if op=='inspect' and args.get('view') in {'inventory','spells'}:
                if args.keys()-{'view','query','page','limit','topic'}:raise BridgeError('invalid_arguments')
                value=self.command('inspect',{'view':args['view']})
                key='items' if args['view']=='inventory' else 'spells'
                if getattr(self,'full_observations',False) and not any(k in args for k in ('query','limit')) and not args.get('page'):return value
                value[key],meta=information.page_rows(value.get(key,[]),args)
                return {**value,**meta}
            before=self.latest_observation
            portal=None
            if op=='interact' or op=='act' and args.get('trigger')=='Activate':
                ref=args.get('ref') if op=='interact' else args.get('target')
                door=next((x for x in (before or {}).get('scene',{}).get('objects',[]) if x.get('ref')==ref and x.get('kind')=='door'),None)
                if door:
                    node=self.atlas.anchor_node()
                    if node:
                        from .doors import observed_anchor
                        heading=before.get('orientation',{}).get('heading_deg',0)
                        portal=(node['ref'],{**door,'heading_deg':heading,
                                            'anchor':observed_anchor(door,self.atlas.current()['pose'],heading)})
            if op=='sequence':return workflows.sequence(self,args)
            if op in {'rest','buy','travel'}:
                from .services import perform
                return perform(self,op,args)
            if op=='repair':return workflows.repair(self,args)
            if op=='read' and (args.get('all') or args.get('search')):
                result=workflows.read_document(self,args);self.knowledge.ingest('read',result);return result
            if op=='atlas':return workflows.atlas_query(self,args)
            if op=='revisit':return workflows.navigate(self,args)
            if op in {'remember','recall','connect','route'}:
                if op=='remember':
                    if args.keys()-{'label','note','exits','confidence'}:raise BridgeError('invalid_arguments')
                    place=self.memory.remember(args.get('label'),args.get('note',''),args.get('exits',[]),
                                                args.get('confidence','observed'),self.latest_observation)
                    if self.latest_observation.get('ui_mode')=='Gameplay' and self.latest_observation.get('body',{}).get('on_ground') and not self.latest_observation.get('body',{}).get('swimming') and not self.latest_observation.get('body',{}).get('dead'):
                        place['motor_ref']=self.command('mark')['ref'];self.memory.persist()
                        node=self.atlas.anchor_node(place['label'])
                        if node:place['atlas_node']=node['ref'];self.memory.persist()
                    return place
                if op=='recall':
                    if args.keys()-{'query','archived'}:raise BridgeError('invalid_arguments')
                    return self.memory.recall(args.get('query',''),args.get('archived',False))
                if op=='connect':
                    if args.keys()-{'from','to','via'}:raise BridgeError('invalid_arguments')
                    return self.memory.connect(args.get('from'),args.get('to'),args.get('via'))
                if args:raise BridgeError('invalid_arguments')
                return self.memory.route()
            if op=='scan':
                if args.keys()-{'pitch_deg'}:raise BridgeError('invalid_arguments')
                return self.scan(number(args.get('pitch_deg',0),-80,80))
            if op=='retreat':
                if args.keys()-{'ref','meters','seconds','run','actions'}:raise BridgeError('invalid_arguments')
                return self.call('evade',{'direction':'back',**args})
            if op=='evade' and 'actions' in args:
                validate(op,args)
                chain={'actions':args['actions'],'max_seconds':args.get('seconds',4),
                    'movement':{'direction':args['direction'],'meters':args.get('meters',2),'run':args.get('run',False),'face_target':True}}
                if 'ref' in args:chain['ref']=args['ref']
                return self.call('chain',chain)
            if op=='return_to':
                if args.keys()-{'ref','run','seconds','under_fire'}:raise BridgeError('invalid_arguments')
                place=next((p for p in self.memory.data['places'] if p['ref']==args.get('ref')),None)
                if not place:raise BridgeError('unknown_place')
                if place.get('atlas_node'):
                    return workflows.navigate(self,{**args,'ref':place['atlas_node']})
                if place.get('branch')!=self.memory.data['branch'] or not place.get('motor_ref'):raise BridgeError('unknown_place')
                return self.call('go',{**args,'ref':place['motor_ref']})
            if op == "status":
                if args.keys()-{'player'} or ('player' in args and type(args['player']) is not bool):
                    raise BridgeError('invalid_arguments')
                if args.get('player'):
                    return self.command('inspect',{'view':'character'})
                return {"running": self.process is not None and self.process.poll() is None,
                        "display": self.display.name, "uncertain": self.uncertain,
                        "recording": self.recorder.status() if self.recorder else None}
            if op in {'record_start', 'record_stop', 'record_status'}:
                if args:
                    raise BridgeError('invalid_arguments')
                if op == 'record_start':
                    if self.recorder:
                        raise BridgeError('already_recording')
                    self.command('observe')  # start on a confirmed pause
                    self.recordings_dir.mkdir(parents=True, exist_ok=True)
                    path = self.recordings_dir / (time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.mp4')
                    environment = identity(self.root)
                    atomic_json(path.with_suffix(".environment.json"), environment)
                    self.recorder = Recorder(self.display,path, encoding_options=self.recording_settings)
                    atomic_json(path.with_suffix('.environment.json'), {**environment, 'recording_encoder': self.recorder.encoding})
                    return self.recorder.status()
                if op == 'record_stop':
                    return self.stop_recording()
                return self.recorder.status() if self.recorder else self.last_recording or {'recording': False}
            if op == 'save':
                validate(op, args)
                self.command('observe')
                existing = {self.atlas.save_key(s) for s in self.command('saves')['saves']}
                result = self.command('save', args)
                created = [s for s in result['saves'] if s['description'] == args['description'] and self.atlas.save_key(s) not in existing]
                if len(created)!=1:raise BridgeError('save_confirmation_missing')
                self.atlas.checkpoint(created[0])
                result={'saved':created[0],'total_saves':len(result['saves'])}
            elif op == "restart":
                if args.keys() - {"load_latest"} or ("load_latest" in args and type(args["load_latest"]) is not bool):
                    raise BridgeError("invalid_arguments")
                self.stop_game()
                self.launch()
                if args.get("load_latest"):
                    slots = self.command("saves")["saves"]
                    if not slots:
                        raise BridgeError("no_saves")
                    self.command("load", {"ref": slots[0]["ref"]}, timeout=100)
                    self.memory.branch('load_latest')
                result = self.observe()
            elif op=='hover':
                if set(args)!={'ref'} or not isinstance(args['ref'],str):raise BridgeError('invalid_arguments')
                if self.latest_observation and self.latest_observation.get('ui_mode')=='Gameplay':raise BridgeError('ui_required')
                self._check_ui({'observation':self.latest_observation['observation'] if self.latest_observation else None})
                current=self.command('ui')
                matches=[e for e in current.get('elements',[]) if e['ref']==args['ref']]
                if len(matches)!=1:raise BridgeError('stale_ui_ref')
                if matches[0].get('screen_visible') is False or 'rect' not in matches[0]:
                    raise BridgeError('ui_element_offscreen')
                with self.record_ui():
                    self.command('ui_hover',{'ref':args['ref']})
                    time.sleep(.8)
                    result=self.observe()
            elif op in {"click", "key", "text", "scroll"}:
                fields = {"click": {"x", "y", "button", "observation"},
                          "key": {"key", "observation"}, "text": {"text", "observation"},
                          "scroll": {"steps", "observation"}}[op]
                if args.keys() - fields:
                    raise BridgeError("invalid_arguments")
                self._check_ui(args)
                self.latest_observation = None
                with self.record_ui():
                    if op == "click":
                        self.display.click(args.get("x"), args.get("y"), args.get("button", 1))
                    elif op == "key":
                        self.display.key(args.get("key"))
                    elif op == "text":
                        self.display.text(args.get("text"))
                    else:
                        steps = number(args.get("steps"), -10, 10)
                        if type(steps) is not int:
                            raise BridgeError("invalid_arguments")
                        self.command('ui_scroll',{'steps':steps})
                    time.sleep(.12)
                    result = self.observe()
            elif op == "observe":
                if args.keys()-{'no_screenshot','map'}:raise BridgeError('invalid_arguments')
                result = self.observe(capture=not args.get('no_screenshot',False),maps=args.get('map',False))
            else:
                if op=='pick' or op=='walk' and 'ref' not in args:
                    validate(op,args)
                    self._check_ui(args)
                    if self.latest_observation['ui_mode']!='Gameplay':raise BridgeError('ui_open')
                if op=='choose' and isinstance(args.get('ref'),str) and not args['ref'].startswith('ui_'):
                    current=self.command('ui')
                    matches=[e for e in current.get('elements',[]) if e['enabled'] and e['text']==args['ref']]
                    if not matches and any(e['text']==args['ref'] and not e['enabled'] and e['role'] in ('button','link','item','item_slot','input','list_item') for e in current.get('elements',[])):
                        raise BridgeError('ui_control_disabled')
                    buttons=[e for e in matches if e['role']=='button']
                    matches=buttons or matches
                    if len(matches)!=1:raise BridgeError('ui_choice_missing_or_ambiguous')
                    args={'ref':matches[0]['ref']}
                if op == "trigger" and args.get("name") not in {"Inventory", "Journal", "GameMenu", "Rest"}:
                    validate(op,args)
                    result = self.command("act", {"trigger":args["name"],"seconds":0.1},timeout=60)
                elif op == 'trigger':
                    with self.record_ui():
                        validate(op,args)
                        if args['name'] in {'GameMenu','Rest'}:
                            current=self.command('observe')
                            if args['name']=='Rest' and current.get('ui_mode')!='Gameplay':
                                raise BridgeError('ui_open')
                            self.display.focus(self.process.pid)
                            if args['name']=='GameMenu':self.display.key('escape')
                            else:
                                result = self.command('trigger', {'name':'Rest'})
                            if args['name']=='GameMenu': result = {'paused':True,'submitted':True}
                        else:
                            result = self.command(op,args)
                        time.sleep(.15)
                elif op in {'choose','edit','adjust','map','use_item','select_spell','select_enchanted','fov'}:
                    # These change the visible game UI without resuming world
                    # simulation. Keep their rendered result in the test video.
                    with self.record_ui():
                        result = self.command(op, args)
                        time.sleep(.12)
                else:
                    timeout=100 if op in {"load", "new_game"} else 70 if op in {'fly','swim'} else 60 if op in {'act','look','focus','approach','move_local','walk','go','evade','track','lock','strike','cast','chain','interact','wait_until'} else 25
                    result = self.command(op, args, timeout=timeout)
                if op in {"act", "look", "trigger", "use_item", "select_spell", "select_enchanted", "load", "new_game", "stop",
                          "focus","approach","interact","wait_until","move_local","walk","go","fly","swim","evade","survey","fov","choose","edit","adjust","map","track","lock","unlock","strike","cast","chain","resetNPC"}:
                    if op in {'load','new_game'}:self.memory.branch(op)
                    if op in {'load','new_game'}:self.latest_observation = None
                    # Return one canonical observation instead of embedded stale data.
                    result.pop("observation", None)
                    result = {"action": result, "observation": self.observe()}
                    if op not in {'load','new_game'}:
                        changes=observation_changes(before,result['observation'])
                        if changes:result['action']['changes']=changes
                    if portal and result['action'].get('outcome')=='location_changed':
                        destination=self.atlas.anchor_node()
                        origin_space,_=self.atlas.find_node(portal[0])
                        if destination and origin_space:
                            active=self.atlas.segment
                            try:
                                self.atlas.segment=origin_space['ref']
                                origin=self.atlas.anchor_node()
                            finally:self.atlas.segment=active
                            self.atlas.add_transition(origin['ref'],destination['ref'],{**portal[1],'heading_deg':origin_space['heading']})
                    result['feedback']=feedback(op,result['action'],before,result['observation'],args)
                    if result['feedback']['reason']=='player_down':
                        result['action']['reason']='player_down';result['action']['outcome']='interrupted'
                    self.memory.record_step(op,args,result['action'],result['observation'])
            with open(self.runtime / "actions.jsonl", "a") as log:
                log.write(json.dumps({"op": op, "args": args, "result": present_response(result),
                                      "wall_seconds": round(time.monotonic()-started, 3)}, ensure_ascii=False) + "\n")
            return result

    def stop_game(self):
        if self.recorder:
            if self.process and self.process.poll() is None:
                try: self.command('stop',timeout=3)
                except BridgeError: pass
            # Finalize while the engine can acknowledge the last sample/frame.
            # Restart must also release transports before launch replaces them.
            self.stop_recording()
        if not self.process:
            return
        if self.process.poll() is None:
            try:
                self.command("quit", timeout=3)
                self.process.wait(timeout=4)
            except (BridgeError, subprocess.TimeoutExpired):
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=3)
        if self.reader:
            self.reader.join(timeout=2)
        self.process = None
        self.display.window = None

    def close(self):
        self.stop_game()
        self.stop_recording()
        self.display.stop()
