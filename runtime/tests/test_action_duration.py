from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from astra_bridge.protocol import BridgeError, validate
from astra_bridge.session import Session


@pytest.mark.parametrize('seconds', [3.01, 10, 140, 3600])
def test_caller_can_choose_long_durations(seconds):
    validate('act', {'seconds': seconds, 'move': 1})
    validate('track', {'ref': 'visible_test', 'seconds': seconds})
    validate('chain', {'actions': [{'op': 'wait', 'seconds': seconds}]})


@pytest.mark.parametrize('seconds', [-1, 0, .01, True, '10', float('nan'), float('inf')])
@pytest.mark.parametrize('op', ['act', 'track', 'chain'])
def test_duration_still_requires_a_finite_positive_number(op, seconds):
    args = {'actions': [{'op': 'wait', 'seconds': seconds}]} if op == 'chain' else {'seconds': seconds}
    if op == 'track': args['ref'] = 'visible_test'
    with pytest.raises(BridgeError):
        validate(op, args)


@pytest.mark.parametrize('op', ['act', 'track'])
def test_session_waits_for_long_action_result(tmp_path, monkeypatch, op):
    s = Session.__new__(Session)
    s.inbox = tmp_path / 'inbox.json'
    s.knowledge=SimpleNamespace(ingest=lambda *args:None,recognize=lambda *args:None)
    s.atlas=SimpleNamespace(profile='test')
    s.display=SimpleNamespace(public_coordinates=lambda value:value)
    s.process = SimpleNamespace(poll=lambda: None)
    s.uncertain = False; s.command_id = 0; s.session_id = 'test'; s.responses = {}
    s.pending_commands = set()
    clock = [0.0]
    monkeypatch.setattr('astra_bridge.session.time.monotonic', lambda: clock[0])

    class Condition:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def wait(self, seconds):
            clock[0] += seconds
            if clock[0] >= 140:
                s.responses[s.command_id] = {'status': 'completed', 'result': {'elapsed': 140, 'paused': True}}

    s.condition = Condition()
    args = {'seconds': 140}
    if op == 'track': args['ref'] = 'visible_test'
    result = s.command(op, args, timeout=60)
    assert result == {'elapsed': 140, 'paused': True}
    assert not s.uncertain


def test_cli_waits_beyond_the_old_socket_timeout(monkeypatch):
    from astra_bridge.cli import request
    budgets = []

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, seconds): budgets.append(seconds)
        def connect(self, path): pass
        def sendall(self, data): pass
        def makefile(self, mode): return self
        def readline(self, limit):
            assert budgets[-1] > 140 + 25  # action plus final observation
            return b'{"ok":true,"result":{"elapsed":140}}\n'

    monkeypatch.setattr('astra_bridge.cli.socket.socket', lambda *args: Connection())
    assert request('act', {'seconds': 140})['ok']
    assert request('track', {'seconds': 140})['ok']


def test_menu_dispatcher_allows_long_actions_and_keeps_timeout_recovery():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(['lua', 'tests/action_duration.lua'], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
