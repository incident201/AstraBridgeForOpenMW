"""Explicit ownership survives short CLI connections, never daemon restarts."""
from dataclasses import dataclass
import secrets
import time

from astra_bridge.protocol import BridgeError


@dataclass
class Ownership:
    mode: str = 'idle'
    token: str | None = None
    name: str | None = None
    since: float | None = None

    def public(self):
        return {'mode':self.mode,'name':self.name,'since':self.since}

    def acquire_agent(self, name):
        if self.mode=='agent': raise BridgeError('agent_already_connected')
        if not isinstance(name,str) or not 1<=len(name)<=100: raise BridgeError('invalid_agent_name')
        self.mode,self.token,self.name,self.since='agent',secrets.token_urlsafe(32),name,time.time()
        return {'session_token':self.token,**self.public()}

    def verify_agent(self, token):
        if self.mode!='agent' or not isinstance(token,str) or not secrets.compare_digest(token,self.token or ''):
            raise BridgeError('agent_not_connected')

    def acquire_manual(self, token):
        if self.mode=='agent':raise BridgeError('agent_owns_input')
        if self.mode=='manual' and self.token!=token:raise BridgeError('manual_input_busy')
        self.mode,self.token,self.name,self.since='manual',token,'Manual control',time.time()

    def release(self):
        self.mode,self.token,self.name,self.since='idle',None,None,None
