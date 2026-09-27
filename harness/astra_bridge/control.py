"""One gameplay owner, with cancellation and progress independent of that owner."""
from __future__ import annotations

import threading
import time
import uuid

from .protocol import BridgeError, atomic_json, validate
from .observations import present_response


class Control:
    def __init__(self, session):
        self.session = session
        self.owner = threading.Lock()
        self.cancelled = threading.Event()
        self.cancel_writer = threading.Lock()
        self.active = None

    def progress(self, result):
        if self.active is not None:
            self.active = {**self.active, **result}

    def status(self):
        active = self.active
        if active is None:
            return None
        return {**{k: v for k, v in active.items() if k != 'started'},
                'wall_seconds': round(time.monotonic() - active['started'], 3)}

    def interrupt(self):
        self.cancelled.set()
        with self.cancel_writer:
            atomic_json(self.session.inbox.with_name('cancel.json'),
                        {'session': self.session.session_id, 'token': uuid.uuid4().hex})

    def execute(self, op, args):
        s = self.session
        if not isinstance(args, dict):
            raise BridgeError('invalid_arguments')
        args = dict(args)
        full = args.pop('full',False)
        if type(full) is not bool: raise BridgeError('invalid_arguments')
        if op == 'status' and not args.get('player'):
            if args.keys() - {'player'}: raise BridgeError('invalid_arguments')
            return {'running': s.process is not None and s.process.poll() is None,
                    'display': s.display.name, 'uncertain': s.uncertain,
                    'recording': s.recorder.status() if s.recorder else None,
                    'active_action': self.status()}
        if op in {'stop', 'shutdown'}:
            if args: raise BridgeError('invalid_arguments')
            self.interrupt()
            with self.owner:
                try:
                    if op == 'shutdown':
                        s.close()
                        return {'stopped': True}
                    return present_response(s.call('stop', args), full)
                finally:
                    self.cancelled.clear()
        if not self.owner.acquire(blocking=False):
            raise BridgeError('controller_busy_use_status_or_stop')
        try:
            self.cancelled.clear()
            self.active = {'operation': op, 'phase': 'starting', 'started': time.monotonic()}
            s.full_observations=full
            before = s.latest_observation
            return present_response(s.call(op, args), full, before)
        finally:
            self.active = None
            s.full_observations=False
            self.owner.release()
