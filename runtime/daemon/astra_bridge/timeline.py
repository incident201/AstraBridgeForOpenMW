"""Public session commentary and command history, aligned with source media."""
from collections import deque
import json
import logging
import math
from pathlib import Path
import threading
import time
import uuid

from .protocol import BridgeError


class Timeline:
    def __init__(self, session):
        self.session=session
        self.lock=threading.RLock()
        self.rows=deque(maxlen=80)
        self.active_actions={}
        self.agent_started=None
        self.wall_seconds=0.0
        self.game_seconds=0.0
        self.simulation=None
        self.world_active=False
        self.clock_sample=None

    def agent(self, connected):
        with self.lock:
            if self.agent_started is not None:
                self.wall_seconds+=time.monotonic()-self.agent_started
            self.agent_started=time.monotonic() if connected else None
            self.recording_clock(force=True)

    def simulation_tick(self, seconds, active):
        with self.lock:
            if isinstance(seconds,(int,float)) and math.isfinite(seconds):
                if self.simulation is not None:self.game_seconds+=max(0,seconds-self.simulation)
                self.simulation=seconds
            self.world_active=active
            self.recording_clock()

    def clocks(self):
        with self.lock:
            wall=self.wall_seconds+(time.monotonic()-self.agent_started if self.agent_started is not None else 0)
            return {'wall_seconds':round(wall,3),'game_seconds':round(self.game_seconds,3),
                    'wall_active':self.agent_started is not None,'game_active':self.world_active}

    def recent(self):
        with self.lock:
            rows=list(self.rows);ids={row['id'] for row in rows}
            return rows+[row for row in self.active_actions.values() if row['id'] not in ids]

    def emit(self, kind, **fields):
        with self.lock:
            s=self.session
            row={'id':uuid.uuid4().hex,'kind':kind,'session':s.session_id,'time':time.time(),**self.clocks(),**fields}
            recorder=s.recorder
            if recorder and not recorder.closing:
                row.update(recording=recorder.path.name,recording_seconds=fields.get('recording_seconds',round(max(0,recorder.media.samples-recorder.base_sample)/48000,6)))
            if kind not in {'clock','snapshot'}:self.rows.append(row)
            if kind=='action':
                if fields['state']=='active':self.active_actions[fields['action_id']]=row
                else:self.active_actions.pop(fields['action_id'],None)
            directory=s.runtime.parent/'sessions'
            directory.mkdir(parents=True,exist_ok=True)
            encoded=json.dumps(row,ensure_ascii=False)+'\n'
            try:
                with (directory/(s.session_id+'.timeline.jsonl')).open('a') as stream:stream.write(encoded)
                if recorder and not recorder.closing:
                    with recorder.path.with_suffix('.events.jsonl').open('a') as stream:stream.write(encoded)
            except OSError:
                if kind=='comment':raise
                logging.exception('Could not persist action timeline')
            return row

    def recording_started(self):
        with self.lock:
            self.clock_sample=None
            # Seed messages/actions already on screen at the first recorded frame.
            rows=self.recent();actions={row['action_id']:row for row in rows if row['kind']=='action'}
            snapshot=[row for row in rows if row['kind']=='comment'][-3:]
            snapshot += [row for row in actions.values() if row['state']!='active'][-4:]
            snapshot += [row for row in actions.values() if row['state']=='active']
            self.emit('snapshot',events=snapshot,recording_seconds=0)
            self.recording_clock(force=True)

    def recording_clock(self, force=False):
        recorder=self.session.recorder
        if not recorder or recorder.closing:return
        sample=recorder.media.samples
        if force or self.clock_sample is None or sample-self.clock_sample>=12000:
            self.clock_sample=sample
            self.emit('clock')

    def comment(self, args):
        args=dict(args)
        if 'full' in args:
            if type(args.pop('full')) is not bool:raise BridgeError('invalid_arguments')
        if set(args)!={'text'} or not isinstance(args['text'],str) or not args['text'].strip() or len(args['text'].encode('utf8'))>4096:
            raise BridgeError('invalid_arguments',message='Comment text must contain 1–4096 UTF-8 bytes')
        return self.emit('comment',text=args['text'].strip())
