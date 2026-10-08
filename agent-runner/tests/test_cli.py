import json

from astrabridge_runner.main import main
from astrabridge_runner.locking import FileLock
from test_api_loop import FakeDeepSeek, reply, call


def test_cli_new_session_and_resume_restore_native_history(fixture, monkeypatch):
    f = fixture
    server = FakeDeepSeek([reply(0, [call('astra_observe', {}, 'frame')]), reply(1, content='First goal done.'),
                           reply(2, [call('astra_act', {'move': 1, 'seconds': .2}, 'move')]), reply(3, content='Second goal done.')])
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'secret-test-key')
    monkeypatch.setattr('builtins.input', lambda _: '/quit')
    sessions = f['root']/'cli-sessions'
    try:
        assert main(['run','--provider','deepseek','--model','deepseek-flash','--reasoning','max',
                     '--skill',str(f['skill']),'--base-url',server.url,'--log-dir',str(sessions),'--task','First goal']) == 0
        folder = next(path for path in sessions.iterdir() if path.is_dir())
        assert main(['resume',str(folder),'--task','Second goal']) == 0
        data = json.dumps(server.requests[-1])
        assert 'First goal' in data and 'Second goal' in data and 'Full reasoning 0' in data
        assert 'historical' in data
        calls = [json.loads(row) for row in (f['root']/'calls.jsonl').read_text().splitlines()]
        assert sum(row['args'][:2] == ['game','act'] for row in calls) == 1
        assert json.loads((f['root']/'state.json').read_text())['owner']['mode'] == 'idle'
        assert not (sessions/'.create.lock').is_dir()
    finally: server.close()


def test_session_lock_blocks_concurrent_resume(tmp_path):
    path = tmp_path/'.session.lock'
    with FileLock(path, blocking=False):
        import pytest
        with pytest.raises(RuntimeError, match='already active'):
            with FileLock(path, blocking=False): pass


def test_auth_status_does_not_create_a_registration(tmp_path, capsys):
    root = tmp_path/'auth'
    assert main(['--auth-dir',str(root),'auth','status']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {'active':None,'accounts':[]}
    assert not root.exists()
