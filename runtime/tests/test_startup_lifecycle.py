import asyncio
import threading
from types import SimpleNamespace
import pytest
from astra_bridge.protocol import BridgeError
from astra_daemon.runtime import Runtime


@pytest.mark.asyncio
async def test_stop_cancels_loading_before_waiting_for_startup_lock(tmp_path):
    r=Runtime(tmp_path/'install',tmp_path/'state',tmp_path/'game');entered=threading.Event();abort=threading.Event()
    def start(_):
        r.session=SimpleNamespace(ready=False,process=SimpleNamespace(poll=lambda:None),abort_startup=lambda:abort.set())
        entered.set();assert abort.wait(3);raise BridgeError('game_exited')
    r._start_engine=start;r._stop_engine=lambda:setattr(r,'session',None)
    r.status=lambda:{'running':r.running(),'starting':r.starting,'error':r.last_error}
    pending=asyncio.create_task(r.start_engine());await asyncio.to_thread(entered.wait,1)
    assert not r.running() and r.starting
    stopped=await asyncio.wait_for(r.stop_engine(),1)
    assert not stopped['starting'] and not stopped['running']
    with pytest.raises(BridgeError,match='startup_cancelled'):await pending
    assert r.last_error is None


@pytest.mark.asyncio
async def test_startup_failure_retains_actionable_error_without_reporting_running(tmp_path):
    r=Runtime(tmp_path/'install',tmp_path/'state',tmp_path/'game')
    def fail(_):raise BridgeError('content_load_order',message='Bloodmoon.esm must load after Morrowind.esm.')
    r._start_engine=fail
    with pytest.raises(BridgeError,match='content_load_order'):await r.start_engine()
    assert not r.running() and not r.starting
    assert 'must load after' in r.status()['error']
