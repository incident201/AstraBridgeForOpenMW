import threading
from types import SimpleNamespace
import pytest
from astra_bridge.protocol import BridgeError
from astra_daemon.runtime import Runtime


def fixture(tmp_path, failure=False, state='running'):
    runtime=Runtime(tmp_path/'install',tmp_path/'state',tmp_path/'game');calls=[]
    runtime.owner.acquire_agent('Agent')
    def command(op,**kwargs):
        calls.append(op);return {'state':state}
    def call(op,args):
        assert op=='save';calls.append(op)
        if failure:raise BridgeError('save_unavailable')
        return {'saved':{'description':args['description'],'checkpoint_key':'checkpoint'}}
    recorder=SimpleNamespace(set_active=lambda *a:calls.append('recorder-paused'))
    runtime.session=SimpleNamespace(session_id='session',control=SimpleNamespace(owner=threading.Lock(),cancelled=threading.Event(),interrupt=lambda:calls.append('interrupt')),
        lock=threading.RLock(),timeline=SimpleNamespace(agent=lambda *a:None,emit=lambda *a,**kw:None),
        display=SimpleNamespace(media_stream=SimpleNamespace(ui=lambda *a:None)),recorder=recorder,command=command,call=call)
    runtime.running=lambda:True
    return runtime,calls,recorder

@pytest.mark.asyncio
async def test_save_is_confirmed_before_stop_and_preparation_is_idempotent(tmp_path):
    r,calls,recorder=fixture(tmp_path)
    first=await r.prepare_stop();second=await r.prepare_stop()
    assert first==second and first['save']['status']=='saved'
    assert calls.count('save')==1 and r.session.recorder is recorder
    assert r.owner.mode=='idle' and r.termination['reason']=='user_requested_stop'
    with pytest.raises(BridgeError,match='session_stop_pending'):await r.manual('viewer',True)

@pytest.mark.asyncio
async def test_cancel_after_save_failure_keeps_game_and_recorder(tmp_path):
    r,calls,recorder=fixture(tmp_path,True)
    result=await r.prepare_stop();assert result['save']=={'status':'failed','reason':'save_unavailable'}
    assert r.session.recorder is recorder and r.running()
    assert await r.cancel_stop('wrong-token')=={'cancelled':False}
    assert await r.cancel_stop(result['token'])=={'cancelled':True}
    assert r.running() and r.session.recorder is recorder and r.termination is None and r.stop_preparation is None

@pytest.mark.asyncio
async def test_main_menu_does_not_need_a_save(tmp_path):
    r,calls,_=fixture(tmp_path,state='menu');result=await r.prepare_stop()
    assert result['save']['status']=='not_needed' and 'save' not in calls

@pytest.mark.asyncio
async def test_startup_can_still_be_cancelled_without_waiting_for_save(tmp_path):
    r,_,_=fixture(tmp_path);r.starting=True
    async with r.mutation:assert (await r.prepare_stop())['save']['reason']=='starting'
