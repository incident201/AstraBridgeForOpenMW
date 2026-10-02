"""One gameplay owner, with cancellation and progress independent of that owner."""
from __future__ import annotations

import threading
import time
import uuid

from .protocol import BridgeError, atomic_json, validate
from .observations import present_response
from .receipts import Receipts
from .autosave import finish_session
from .information import receipt_details


class Control:
    def __init__(self, session):
        self.session = session
        self.owner = threading.Lock()
        self.cancelled = threading.Event()
        self.cancel_writer = threading.Lock()
        self.active = None
        self.receipts = Receipts(getattr(session,'runtime',session.inbox.parent)/'action-results.sqlite3')

    def progress(self, result):
        if self.active is not None:
            result=dict(result)
            operation=result.pop('operation',None)
            if operation and operation!=self.active['operation']:
                result['step_operation']=operation
                if 'elapsed' in result:
                    result['step_elapsed']=result['elapsed']
                    result['elapsed']=self.active.get('sequence_elapsed',0)+result['elapsed']
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
        request_id=args.pop('request_id',None)
        if type(full) is not bool: raise BridgeError('invalid_arguments')
        if op=='action_result':
            receipt=self.receipts.get(args.get('ref'))
            if args.keys()-{'ref'}:return receipt_details(receipt,args)
            if 'response' in receipt:receipt['response']=present_response(receipt['response'],full)
            return receipt
        if op == 'status' and not args.get('player'):
            if args.keys() - {'player'}: raise BridgeError('invalid_arguments')
            return {'running': s.process is not None and s.process.poll() is None,
                    'display': s.display.name, 'uncertain': s.uncertain,
                    'recording': s.recorder.status() if s.recorder else None,
                    'active_action': self.status(),
                    **({'autosave':s.autosave.status()} if hasattr(s,'autosave') else {})}
        if op in {'stop', 'shutdown','finish_session'}:
            if args and (op!='finish_session' or args.keys()-{'description'}): raise BridgeError('invalid_arguments')
            self.interrupt()
            with self.owner:
                try:
                    if op=='finish_session':
                        self.cancelled.clear()
                        request_id,previous=self.receipts.begin(op,args,request_id)
                        if previous:return {'replayed':False,**previous}
                        try:
                            result=finish_session(s,args)
                            self.receipts.finish(request_id,result)
                            return {**result,'request_id':request_id}
                        except Exception:
                            self.receipts.finish(request_id,{'error':'finish_session_result_unknown'},'unknown')
                            raise
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
            request_id,previous=self.receipts.begin(op,args,request_id)
            self.active['request_id']=request_id
            if previous:
                if 'response' in previous:previous['response']=present_response(previous['response'],full)
                return {'replayed':False,**previous}
            try:
                result=s.call(op,args)
                if hasattr(s,'autosave') and op not in {'load','new_game','restart','save','autosave','details','knowledge','inspect','ui','read','target_info'}:
                    saved=s.autosave.maybe_save(s)
                    if saved:result['autosave']=saved
                self.receipts.finish(request_id,result)
            except Exception as exc:
                unknown=s.uncertain or str(exc) in {'game_exited','result_unknown_stop_or_restart'} or not isinstance(exc,BridgeError)
                if isinstance(exc,BridgeError):
                    exc.details['request_id']=request_id
                    if not unknown and str(exc) in {'ui_open','stale_ui_ref','action_unavailable'}:
                        observation=s.latest_observation or {}
                        if hasattr(s,'observe'):
                            try:observation=s.observe(capture=False)
                            except BridgeError:pass
                        exc.details['ui_mode']=observation.get('ui_mode')
                        exc.details['body']={k:v for k,v in observation.get('body',{}).items() if k in
                                             {'can_move','dead','controls_enabled','looking_enabled','jumping_enabled','animation_busy','recovering'}}
                        body=observation.get('body',{})
                        exc.details['next_command']='status --player'
                        if str(exc)=='action_unavailable':
                            if body.get('controls_enabled') is False:
                                exc.details.update(reason='player_controls_disabled',next_command='wait-until controls --seconds 10')
                            elif body.get('looking_enabled') is False and (op in {'look','focus','interact','approach','track'} or args.get('yaw') or args.get('pitch')):
                                exc.details.update(reason='player_looking_disabled',next_command='wait-until controls --control looking --seconds 10')
                            elif body.get('jumping_enabled') is False and (op=='jump' or args.get('trigger')=='Jump' or op=='trigger' and args.get('name')=='Jump'):
                                exc.details.update(reason='player_jumping_disabled',next_command='wait-until controls --control jumping --seconds 10')
                            elif body.get('animation_busy') or body.get('recovering'):
                                exc.details['next_command']='wait-until animation --seconds 10'
                        if str(exc) in {'ui_open','stale_ui_ref'} or observation.get('ui_mode')!='Gameplay' or observation.get('ui',{}).get('modal'):
                            exc.details['next_command']='ui'
                failure=exc.response() if isinstance(exc,BridgeError) else {'error':'controller_operation_failed'}
                self.receipts.finish(request_id,failure,'unknown' if unknown else 'rejected')
                raise
            presented=present_response(result, full, before, args.get('ref'))
            if 'details' in presented:presented['details']=presented['details'].replace('REQUEST_ID',request_id)
            return {**presented,'request_id':request_id}
        finally:
            self.active = None
            s.full_observations=False
            self.owner.release()
