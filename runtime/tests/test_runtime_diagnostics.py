from collections import deque
import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from astra_bridge.diagnostic_logs import append_bounded, recent_events
from astra_bridge.protocol import BridgeError
from astra_bridge.session import Session
from astra_daemon.runtime import Runtime


def reader_session(tmp_path):
    session = Session.__new__(Session)
    session.runtime = tmp_path
    session.session_id = 'current'
    session.condition = threading.Condition()
    session.pending_commands = {1}
    session.responses = {}
    session.engine_diagnostics = deque(maxlen=100)
    session.control = SimpleNamespace(cancelled=threading.Event())
    return session


def reply(command_id=1, session='current'):
    return {'version': 1, 'session': session, 'id': command_id,
            'status': 'completed', 'result': {'state': 'running'}}


def protocol_line(value):
    return b'ASTRA_BRIDGE ' + json.dumps(value).encode() + b'\n'


def read_output(session, data, reader_session_id='current'):
    session._read_output(SimpleNamespace(stdout=io.BytesIO(data)), reader_session_id)


def test_engine_log_omits_protocol_chunks_but_delivers_replies(tmp_path):
    session = reader_session(tmp_path)
    chunk = b'ASTRA_PART token 1 1 ' + json.dumps(reply()).encode().hex().encode() + b'\n'
    read_output(session, b'Engine startup\n' + chunk + protocol_line(reply(999)))
    assert session.responses == {1: reply()}
    assert (tmp_path / 'engine-private.log').read_bytes() == b'Engine startup\n'
    assert list(session.engine_diagnostics) == ['Engine startup\n']


def test_full_disk_does_not_stop_reader_or_command_replies(tmp_path, monkeypatch):
    session = reader_session(tmp_path)
    writes = []

    def no_space(*args):
        writes.append(args)
        raise OSError(28, 'No space left on device')

    monkeypatch.setattr('astra_bridge.session.append_bounded', no_space)
    read_output(session, b'Before\n' + protocol_line(reply()) + b'After\n')
    assert session.responses == {1: reply()}
    assert len(writes) == 1
    assert list(session.engine_diagnostics) == ['Before\n', 'After\n']


def test_engine_reader_discards_late_unknown_and_previous_launch_replies(tmp_path):
    session = reader_session(tmp_path)
    read_output(session, b''.join(protocol_line(row) for row in
                                 [reply(0), reply(2), reply(True), reply(1, 'old'), reply()]))
    assert session.responses == {1: reply()}
    session.responses.clear()
    read_output(session, protocol_line(reply(1, 'old')), reader_session_id='old')
    assert session.responses == {}


def test_oversized_stdout_line_is_drained_without_swallowing_next_reply(tmp_path):
    session = reader_session(tmp_path)
    read_output(session, b'x' * 2_000_002 + b'\n' + protocol_line(reply()))
    assert session.responses == {1: reply()}
    assert not (tmp_path / 'engine-private.log').exists()


def test_log_rotation_bounds_existing_and_new_files(tmp_path):
    path = tmp_path / 'engine.log'
    path.write_bytes(b'old' * 100)
    path.with_name('engine.log.1').write_bytes(b'backup' * 100)
    for index in range(12):
        append_bounded(path, f'{index:02d}:abcdefgh\n'.encode(), max_bytes=40, backups=2)
    files = list(tmp_path.iterdir())
    assert len(files) == 3
    assert all(file.stat().st_size <= 40 for file in files)
    assert path.read_bytes().endswith(b'11:abcdefgh\n')


def test_recent_events_reads_across_rotation_and_skips_corruption(tmp_path):
    path = tmp_path / 'events.jsonl'
    path.with_name('events.jsonl.1').write_bytes(b'{"event": "old"}\nnot json\n')
    path.write_bytes(b'{"event": "new"}\n[1, 2]\n{"event": "torn')
    assert recent_events(path) == [{'event': 'old'}, {'event': 'new'}]
    assert recent_events(path, limit=1) == [{'event': 'new'}]


def test_recent_events_has_fixed_read_budget_for_large_files(tmp_path, monkeypatch):
    path = tmp_path / 'events.jsonl'
    with path.open('wb') as stream:
        stream.write(b'{"old":true}\n' * 500_000)
        stream.write(b'{"event":"last"}\n')
    original_open = Path.open
    reads = []

    class Measured:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def seek(self, *args):
            return self.stream.seek(*args)

        def read(self, size):
            reads.append(size)
            return self.stream.read(size)

    def measured_open(file, *args, **kwargs):
        stream = original_open(file, *args, **kwargs)
        return Measured(stream) if file == path else stream

    monkeypatch.setattr(Path, 'open', measured_open)
    assert recent_events(path, max_bytes=64)[-1] == {'event': 'last'}
    assert reads == [64]


def test_session_timeout_removes_waiter_and_late_response(tmp_path, monkeypatch):
    session = reader_session(tmp_path)
    session.pending_commands.clear()
    session.inbox = tmp_path / 'inbox.json'
    session.command_id = 0
    session.uncertain = False
    session.process = SimpleNamespace(poll=lambda: None)
    clock = [0.0]
    monkeypatch.setattr('astra_bridge.session.time.monotonic', lambda: clock[0])

    class Condition:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def wait(self, seconds):
            clock[0] += seconds

        def notify_all(self):
            pass

    session.condition = Condition()
    with pytest.raises(BridgeError, match='result_unknown_stop_or_restart'):
        session.command('ping', timeout=.01)
    assert session.pending_commands == set()
    read_output(session, protocol_line(reply()))
    assert session.responses == {}


def test_session_inbox_write_failure_removes_waiter(tmp_path, monkeypatch):
    session = reader_session(tmp_path)
    session.pending_commands.clear()
    session.inbox = tmp_path / 'inbox.json'
    session.command_id = 0
    session.uncertain = False
    session.process = SimpleNamespace(poll=lambda: None)

    def fail(*args):
        raise OSError(28, 'No space left on device')

    monkeypatch.setattr('astra_bridge.session.atomic_json', fail)
    with pytest.raises(OSError):
        session.command('ping')
    assert session.pending_commands == set()


@pytest.mark.asyncio
async def test_startup_error_uses_current_diagnostics_when_log_rotates(tmp_path):
    runtime = Runtime(tmp_path / 'install', tmp_path / 'state', tmp_path / 'game')
    old_log = runtime.root / 'runtime/engine-private.log'
    old_log.write_text('Fatal error: stale old launch\n')

    def start(_):
        runtime.session = SimpleNamespace(engine_diagnostics=['Fatal error: current failure\n'])
        old_log.rename(old_log.with_name(old_log.name + '.1'))
        old_log.write_text('Later diagnostics\n')
        raise BridgeError('game_exited')

    runtime._start_engine = start
    runtime._stop_engine = lambda: setattr(runtime, 'session', None)
    with pytest.raises(BridgeError, match='game_start_failed') as error:
        await runtime.start_engine()
    assert 'current failure' in error.value.details['message']
    assert 'stale old launch' not in error.value.details['message']


def test_lifecycle_logging_failure_is_nonfatal(tmp_path, monkeypatch):
    runtime = Runtime(tmp_path / 'install', tmp_path / 'state', tmp_path / 'game')

    def fail(*args):
        raise OSError(28, 'No space left on device')

    monkeypatch.setattr('astra_daemon.runtime.append_bounded', fail)
    runtime._history('engine_stopped', session='example')
