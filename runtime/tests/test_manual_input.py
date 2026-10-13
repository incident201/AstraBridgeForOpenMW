import asyncio
import subprocess
import threading
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from astra_bridge.protocol import BridgeError
from astra_daemon.input import Input
from astra_daemon.runtime import Runtime
from astra_daemon.server import application


def text_input():
    inputs = Input.__new__(Input)
    inputs.env = {'DISPLAY': ':private'}
    inputs.lock = threading.RLock()
    inputs.d = object()
    inputs.flush = lambda display: None
    return inputs


@pytest.mark.asyncio
async def test_absolute_pointer_cannot_warp_gameplay_camera(tmp_path):
    runtime = Runtime(tmp_path/'install', tmp_path/'state', tmp_path/'game')
    runtime.owner.acquire_manual('viewer')
    calls = []
    runtime.input = SimpleNamespace(event=calls.append)
    runtime.session = SimpleNamespace(latest_observation={'ui_mode':'Gameplay'})
    await runtime.input_event('viewer', {'type':'pointer','x':.9,'y':.8})
    await runtime.input_event('viewer', {'type':'relative','x':2,'y':1})
    assert calls == [{'type':'relative','x':2,'y':1}]
    runtime.session.latest_observation = {'ui_mode':'Interface'}
    await runtime.input_event('viewer', {'type':'pointer','x':.9,'y':.8})
    assert calls[-1] == {'type':'pointer','x':.9,'y':.8}


@pytest.mark.asyncio
async def test_http_release_does_not_wait_for_websocket_input_backlog(tmp_path):
    runtime = Runtime(tmp_path/'install', tmp_path/'state', tmp_path/'game')
    runtime.running = lambda: True
    runtime._mode = lambda mode: None
    entered = asyncio.Event()
    finish = asyncio.Event()

    async def queued_input(token, event):
        entered.set()
        await finish.wait()

    runtime.input_event = queued_input
    headers = {'Authorization':'Bearer '+'x'*40}
    client = TestClient(TestServer(application(runtime,'x'*40)))
    await client.start_server()
    try:
        socket = await client.ws_connect('/v1/events',headers=headers)
        await socket.send_json({'type':'manual.acquire'})
        while (await socket.receive_json(timeout=1))['type'] != 'input.owner':pass
        await socket.send_json({'type':'input','event':{'type':'relative','x':1,'y':1}})
        await asyncio.wait_for(entered.wait(),1)
        response = await client.post('/v1/runtime/manual/release',headers=headers,json={})
        assert (await response.json())['result']['mode'] == 'idle'
        assert runtime.owner.mode == 'idle'
        runtime.owner.acquire_agent('Player')
        response = await client.post('/v1/runtime/manual/release',headers=headers,json={})
        assert (await response.json())['result']['mode'] == 'agent'
        finish.set()
        await socket.close()
    finally:
        finish.set()
        runtime.owner.release()
        runtime.running = lambda: False
        await client.close()


def test_text_input_has_bounded_delay_for_maximum_length(monkeypatch):
    calls = []
    monkeypatch.setattr('astra_daemon.input.subprocess.run', lambda *args, **kwargs: calls.append((args, kwargs)))
    text_input().event({'type': 'text', 'text': 'x' * 1024})
    arguments, options = calls[0]
    assert arguments[0][:7] == ['xdotool', 'type', '--clearmodifiers', '--delay', '1', '--', 'x' * 1024]
    assert options['timeout'] == 10


@pytest.mark.parametrize('error,code', [
    (subprocess.TimeoutExpired('xdotool', 10), 'input_text_timeout'),
    (subprocess.CalledProcessError(1, 'xdotool'), 'input_text_failed'),
    (FileNotFoundError('xdotool'), 'input_text_unavailable'),
])
def test_text_subprocess_errors_are_bridge_errors(monkeypatch, error, code):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr('astra_daemon.input.subprocess.run', fail)
    with pytest.raises(BridgeError, match=code):
        text_input().event({'type': 'text', 'text': 'hello'})


@pytest.mark.asyncio
async def test_typing_keeps_event_loop_responsive_and_blocks_owner_change(tmp_path):
    runtime = Runtime(tmp_path / 'install', tmp_path / 'state', tmp_path / 'game')
    runtime.owner.acquire_manual('viewer')
    entered = threading.Event()
    finish = threading.Event()

    def type_text(event):
        entered.set()
        assert finish.wait(2)

    runtime.input = SimpleNamespace(event=type_text)
    runtime._mode = lambda mode: None
    typing = asyncio.create_task(runtime.input_event('viewer', {'type': 'text', 'text': 'hello'}))
    release = None
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        assert runtime.mutation.locked()
        # This event-loop timer completes while the blocking input worker waits.
        await asyncio.wait_for(asyncio.sleep(.01), .1)
        release = asyncio.create_task(runtime.manual('viewer', False))
        await asyncio.sleep(.01)
        assert not release.done()
        assert runtime.owner.mode == 'manual'
    finally:
        finish.set()
        await typing
        if release:
            await release
    assert runtime.owner.mode == 'idle'


@pytest.mark.asyncio
async def test_input_cancellation_waits_for_typing_before_unlocking(tmp_path):
    runtime = Runtime(tmp_path / 'install', tmp_path / 'state', tmp_path / 'game')
    runtime.owner.acquire_manual('viewer')
    entered = threading.Event()
    finish = threading.Event()

    def type_text(event):
        entered.set()
        assert finish.wait(2)

    runtime.input = SimpleNamespace(event=type_text)
    typing = asyncio.create_task(runtime.input_event('viewer', {'type': 'text', 'text': 'hello'}))
    assert await asyncio.to_thread(entered.wait, 1)
    typing.cancel()
    await asyncio.sleep(.01)
    assert runtime.mutation.locked()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await typing
    assert not runtime.mutation.locked()


@pytest.mark.asyncio
async def test_websocket_typing_error_preserves_connection_and_other_requests(tmp_path):
    runtime = Runtime(tmp_path / 'install', tmp_path / 'state', tmp_path / 'game')
    runtime.running = lambda: True
    runtime._mode = lambda mode: None
    inputs = text_input()

    def event(value):
        raise BridgeError('input_text_timeout')

    inputs.event = event
    runtime.input = inputs
    headers = {'Authorization': 'Bearer ' + 'x' * 40}
    client = TestClient(TestServer(application(runtime, 'x' * 40)))
    await client.start_server()
    try:
        socket = await client.ws_connect('/v1/events', headers=headers)
        await socket.send_json({'type': 'manual.acquire'})

        async def message(kind):
            while True:
                result = await socket.receive_json(timeout=1)
                if result['type'] == kind:
                    return result

        assert (await message('input.owner'))['data']['mode'] == 'manual'
        await socket.send_json({'type': 'input', 'event': {'type': 'text', 'text': 'hello'}})
        assert (await message('error'))['error'] == 'input_text_timeout'
        assert (await client.get('/health')).status == 200
        assert not socket.closed
        await socket.send_json({'type': 'manual.release'})
        assert (await message('input.owner'))['data']['mode'] == 'idle'
        await socket.close()
    finally:
        runtime.input = None
        runtime.running = lambda: False
        await client.close()


@pytest.mark.asyncio
async def test_sessions_endpoint_tolerates_truncated_history(tmp_path):
    runtime = Runtime(tmp_path / 'install', tmp_path / 'state', tmp_path / 'game')
    (runtime.root / 'sessions/events.jsonl').write_bytes(b'{"event":"started"}\n{"bad":')
    client = TestClient(TestServer(application(runtime, 'x' * 40)))
    await client.start_server()
    try:
        response = await client.get('/v1/runtime/sessions', headers={'Authorization': 'Bearer ' + 'x' * 40})
        assert response.status == 200
        assert (await response.json())['result'] == [{'event': 'started'}]
    finally:
        await client.close()
