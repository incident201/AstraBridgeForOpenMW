"""Simulation-time autosave ring. Only slots created by this ring are overwritten."""
import json
import uuid

from .protocol import BridgeError, atomic_json, number


class Autosave:
    def __init__(self, path):
        self.path=path
        self.data=json.loads(path.read_text()) if path.exists() else {'enabled':True,'interval':300,'slots':3,'namespace':uuid.uuid4().hex[:10],'owned':{},'next':0,'elapsed':0}
        self.clock=None
        self.retry_at=0

    def persist(self): atomic_json(self.path,self.data)

    def configure(self,args):
        if args.keys()-{'enabled','interval','slots'}:raise BridgeError('invalid_arguments')
        if 'enabled' in args and type(args['enabled']) is not bool:raise BridgeError('invalid_arguments')
        if 'interval' in args:number(args['interval'],1,86400)
        if 'slots' in args:
            number(args['slots'],1,100)
            if type(args['slots']) is not int:raise BridgeError('invalid_arguments')
        self.data.update(args);self.persist()
        return self.status()

    def status(self):
        return {k:self.data[k] for k in ('enabled','interval','slots','elapsed','last_success','last_error') if k in self.data}

    def observe(self,observation,reset=False):
        now=observation.get('simulation_seconds')
        if now is None:return
        if not reset and self.clock is not None:self.data['elapsed']+=max(0,now-self.clock)
        self.clock=now

    def maybe_save(self,session):
        if not self.data['enabled'] or self.data['elapsed']<max(self.data['interval'],self.retry_at):return None
        current=session.latest_observation or {}
        if (current.get('state')!='running' or current.get('ui_mode')!='Gameplay'
                or current.get('ui',{}).get('modal') or current.get('body',{}).get('dead')):return None
        index=self.data['next']%self.data['slots'];description=f"Astra auto {self.data['namespace']} {index+1}"
        try:
            saves=session.command('saves')['saves']
            owned=self.data['owned'].get(str(index))
            slot=next((s for s in saves if s.get('checkpoint_key')==owned and s['description']==description),None)
            result=session.command('save',{'description':description},_save_ref=slot['ref'] if slot else None)
            matches=[s for s in result['saves'] if s['description']==description]
            if len(matches)!=1:raise BridgeError('autosave_confirmation_missing')
            saved=matches[0];session.atlas.checkpoint(saved)
            self.data['owned'][str(index)]=saved['checkpoint_key']
            self.data.update(next=(index+1)%self.data['slots'],elapsed=0,last_success={'description':description,'checkpoint_key':saved['checkpoint_key']})
            self.data.pop('last_error',None);self.retry_at=0;self.persist()
            return {'saved':description}
        except BridgeError as exc:
            self.data['last_error']=str(exc);self.retry_at=self.data['elapsed']+10;self.persist()
            return {'deferred':str(exc)}


def finish_session(session,args):
    if args.keys()-{'description'}:raise BridgeError('invalid_arguments')
    stages={}
    try:
        session.call('stop');stages['stop']={'ok':True}
        result=session.call('save',{'description':args.get('description','Astra session end')})
        stages['save']={'ok':True,'saved':result.get('saved')}
    except Exception as exc:
        stage='save' if 'stop' in stages else 'stop'
        stages[stage]={'ok':False,'reason':str(exc) if isinstance(exc,BridgeError) else 'operation_failed'}
        # Finalize the video even when saving fails; preserve the running game.
        try:stages['recording']=session.stop_recording()
        except Exception:stages['recording']={'ok':False,'reason':'recording_finalize_failed'}
        return {'stages':stages,'closed':False,'reason':'save_failed_game_kept_open'}
    try:stages['recording']=session.stop_recording()
    except Exception:
        stages['recording']={'ok':False,'reason':'recording_finalize_failed'}
        return {'stages':stages,'closed':False,'reason':'recording_failed_game_kept_open'}
    session.close();stages['close']={'ok':True}
    return {'stages':stages,'closed':True}
