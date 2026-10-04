import json
from types import SimpleNamespace
import pytest
from astra_bridge.timeline import Timeline
from astra_bridge.control import Control
from astra_bridge.protocol import BridgeError


def fixture(tmp_path):
    session=SimpleNamespace(runtime=tmp_path/'runtime',session_id='session1',recorder=None)
    session.timeline=Timeline(session)
    return session


def test_clocks_count_agent_time_and_simulation_separately(tmp_path,monkeypatch):
    now=[10.0];monkeypatch.setattr('astra_bridge.timeline.time.monotonic',lambda:now[0])
    t=fixture(tmp_path).timeline
    t.simulation_tick(100,False);t.agent(True);now[0]+=5
    t.simulation_tick(102,True);t.simulation_tick(102,False)
    assert t.clocks()==dict(wall_seconds=5,game_seconds=2,wall_active=True,game_active=False)
    t.agent(False);now[0]+=50
    assert t.clocks()['wall_seconds']==5
    t.agent(True);now[0]+=3
    assert t.clocks()['wall_seconds']==8
    t.simulation_tick(10,False)  # simulation reset must not move session time backward
    t.simulation_tick(11,True)
    assert t.clocks()['game_seconds']==3


def test_comment_during_action_is_persisted_and_aligned_with_media(tmp_path):
    s=fixture(tmp_path);video=tmp_path/'Journey.mp4'
    s.recorder=SimpleNamespace(path=video,base_sample=48000,media=SimpleNamespace(samples=120000),closing=False)
    control=Control.__new__(Control);control.session=s
    control._execute=lambda *_:pytest.fail('Comment must not acquire the action owner or call engine')
    row=control.execute('comment',{'text':'Checking the eastern door.'})
    assert row['recording_seconds']==1.5 and row['recording']=='Journey.mp4'
    assert json.loads(video.with_suffix('.events.jsonl').read_text())==row
    assert json.loads((tmp_path/'sessions/session1.timeline.jsonl').read_text())==row
    with pytest.raises(BridgeError):control.execute('comment',{'text':' '})
    with pytest.raises(BridgeError):control.execute('comment',{'text':'я'*2049})
    s.recorder=None
    later=control.execute('comment',{'text':'Recording stopped.'})
    assert 'recording_seconds' not in later
    assert len(video.with_suffix('.events.jsonl').read_text().splitlines())==1


def test_completed_blocked_action_retains_its_outcome_and_failures_are_logged(tmp_path):
    s=fixture(tmp_path);c=Control.__new__(Control);c.session=s
    c._execute=lambda *_:{'summary':{'status':'blocked','reason':'no_horizontal_progress'}}
    result=c.execute('sequence',{})
    rows=s.timeline.recent();assert len(rows)==2
    assert rows[0]['state']=='active' and rows[1]['state']=='finished'
    assert rows[0]['action_id']==rows[1]['action_id']
    assert rows[1]['summary']==result['summary']
    def fail(*_):raise BridgeError('ui_open')
    c._execute=fail
    with pytest.raises(BridgeError):c.execute('move',{})
    assert s.timeline.recent()[-1]['reason']=='ui_open'


def test_active_command_survives_a_long_stream_of_short_queries(tmp_path):
    t=fixture(tmp_path).timeline
    t.emit('action',action_id='long',operation='approach',state='active')
    for i in range(100):
        t.emit('action',action_id=str(i),operation='status',state='active')
        t.emit('action',action_id=str(i),operation='status',state='finished')
    assert any(r.get('action_id')=='long' for r in t.recent())
    t.emit('action',action_id='long',operation='approach',state='finished')
    assert not any(r.get('action_id')=='long' and r['state']=='active' for r in t.recent())
