import threading
from types import SimpleNamespace
import pytest
from astra_bridge.session import Session
from astra_bridge.protocol import BridgeError

def test_hover_reads_disabled_control_without_clicking(tmp_path,monkeypatch):
    s=Session.__new__(Session)
    s.lock=threading.RLock();s.runtime=tmp_path;s.recorder=None
    s.latest_observation={'observation':8,'ui_mode':'Training'}
    s._check_ui=lambda args:None
    calls=[]
    def command(op,args=None):
        if op=='ui':return {'elements':[{'ref':'ui_current','enabled':False,'rect':[20,30,40,20]}]}
        calls.append((op,args));return {'submitted':True}
    s.command=command
    s.display=SimpleNamespace(run=lambda *args:pytest.fail('native hover must not use XTest'))
    s.observe=lambda:{'ui':{'text':'Visible tooltip'},'observation':9}
    monkeypatch.setattr('astra_bridge.session.time.sleep',lambda n:None)
    assert s.call('hover',{'ref':'ui_current'})['ui']['text']=='Visible tooltip'
    assert calls==[('ui_hover',{'ref':'ui_current'})]
    with pytest.raises(BridgeError,match='stale_ui_ref'):s.call('hover',{'ref':'ui_old'})
    assert len(calls)==1
    s.latest_observation['ui_mode']='Gameplay'
    with pytest.raises(BridgeError,match='ui_required'):s.call('hover',{'ref':'ui_current'})
    assert len(calls)==1,'hover must never rotate the camera in gameplay'


def test_offscreen_topic_is_semantic_only(tmp_path):
    s=Session.__new__(Session)
    s.lock=threading.RLock();s.runtime=tmp_path;s.recorder=None
    s.latest_observation={'observation':8,'ui_mode':'Dialogue'}
    s._check_ui=lambda args:None
    s.command=lambda op:{'elements':[{'ref':'ui_topic','enabled':True,'screen_visible':False}]}
    with pytest.raises(BridgeError,match='ui_element_offscreen'):
        s.call('hover',{'ref':'ui_topic'})


def test_scroll_uses_native_wheel_not_xtest(tmp_path,monkeypatch):
    s=Session.__new__(Session)
    s.lock=threading.RLock();s.runtime=tmp_path;s.recorder=None
    s.latest_observation={'observation':8,'ui_mode':'Dialogue'}
    s._check_ui=lambda args:None
    calls=[]
    s.command=lambda op,args:calls.append((op,args))
    s.display=SimpleNamespace(run=lambda *args:pytest.fail('native scroll must not use XTest'))
    s.observe=lambda:{'observation':9}
    monkeypatch.setattr('astra_bridge.session.time.sleep',lambda n:None)
    assert s.call('scroll',{'steps':-4,'observation':8})=={'observation':9}
    assert calls==[('ui_scroll',{'steps':-4})]
