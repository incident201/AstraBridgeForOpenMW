import json
from types import SimpleNamespace

import httpx
import pytest

from astrabridge_runner.history import History
from astrabridge_runner.journal import Journal
from astrabridge_runner.logs import prune_sessions
from astrabridge_runner.main import main, provider
from astrabridge_runner.providers.grok import Grok
from test_grok import KEY, Server, catalog_provider, response


def test_grok_requires_its_own_api_key_without_falling_back(tmp_path, monkeypatch):
    monkeypatch.delenv('XAI_API_KEY', raising=False)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'unrelated-deepseek-key')
    monkeypatch.setenv('OPENAI_API_KEY', 'unrelated-openai-key')
    journal = Journal(tmp_path)
    try:
        with pytest.raises(ValueError, match='Set XAI_API_KEY'):
            provider('grok', journal, SimpleNamespace(), 'grok-4.7', 'xhigh')
    finally:
        journal.close()


def test_grok_key_selects_xai_provider_and_reasoning_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv('XAI_API_KEY', KEY)
    journal = Journal(tmp_path)
    api = provider('grok', journal, SimpleNamespace(), 'grok-4.7', 'xhigh')
    try:
        assert isinstance(api, Grok)
        assert api.headers() == {'Authorization': 'Bearer ' + KEY}
        assert str(api.http.client.base_url) == 'https://api.x.ai/v1/'
        assert api.http.client.timeout.read == 3600
        assert api.http.client.timeout.connect == 10
    finally:
        api.close()
        journal.close()


def test_grok_cli_new_session_and_resume(fixture, monkeypatch):
    server = Server([
        response(0, 'astra_observe'), response(1, text='First goal done.'),
        response(2, 'astra_act', {'move': 1, 'seconds': .2}), response(3, text='Second goal done.'),
    ])
    keys = []

    def factory(key, journal, model, effort):
        keys.append(key)
        assert (model, effort) == ('grok-4.7', 'xhigh')
        return server.provider(journal)

    monkeypatch.setattr('astrabridge_runner.main.Grok', factory)
    monkeypatch.setenv('XAI_API_KEY', KEY)
    monkeypatch.setattr('builtins.input', lambda _: '/quit')
    sessions = fixture['root'] / 'grok-cli-sessions'
    assert main(['run', '--provider', 'grok', '--model', 'grok-4.7', '--reasoning', 'xhigh',
                 '--skill', str(fixture['skill']), '--log-dir', str(sessions), '--task', 'First goal']) == 0
    folder = next(path for path in sessions.iterdir() if path.is_dir())
    assert main(['resume', str(folder), '--task', 'Second goal']) == 0
    assert keys == [KEY, KEY]
    payload = json.dumps(server.requests[-1])
    assert 'First goal' in payload and 'Second goal' in payload
    assert 'grok-encrypted-reasoning-0' in payload
    assert server.requests[-1]['prompt_cache_key'] == server.requests[0]['prompt_cache_key']
    calls = [json.loads(line) for line in (fixture['root'] / 'calls.jsonl').read_text().splitlines()]
    assert sum(call['args'][:2] == ['game', 'act'] for call in calls) == 1
    assert all(not call['has_key'] for call in calls)


def test_grok_discovery_cli_has_no_game_side_effects(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('XAI_API_KEY', KEY)
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path))
    monkeypatch.setattr('astrabridge_runner.main.Grok', lambda key, journal, model, effort:
                        catalog_provider(journal, [{'id': 'grok-4.7', 'input_modalities': ['text', 'image']}]))
    assert main(['models', '--provider', 'grok', '--json']) == 0
    models = json.loads(capsys.readouterr().out)
    assert models[0]['id'] == 'grok-4.7' and models[0]['context_window'] == 500000


def test_grok_archive_cleanup_uses_existing_retention(tmp_path):
    journal = Journal(tmp_path)
    journal.write('manifest.json', {'schema': 1, 'provider': 'grok'})
    folder = journal.root
    journal.close()
    selected = prune_sessions(tmp_path, older_than_days=0, keep_last=0)
    assert [item['path'] for item in selected['sessions']] == [str(folder)]
    assert selected['dry_run'] and folder.exists()


@pytest.mark.parametrize('usage, expected_output', [
    ({'prompt_tokens': 32, 'completion_tokens': 9, 'reasoning_tokens': 110, 'total_tokens': 151}, 119),
    ({'input_tokens': 32, 'output_tokens': 119, 'output_tokens_details': {'reasoning_tokens': 110}, 'total_tokens': 151}, 119),
    ({'prompt_tokens': 32, 'completion_tokens': 119, 'completion_tokens_details': {'reasoning_tokens': 110}, 'total_tokens': 151}, 119),
])
def test_grok_reasoning_usage_counts_once_and_remains_in_context_budget(tmp_path, usage, expected_output):
    journal = Journal(tmp_path)
    api = Grok(KEY, journal, client=httpx.Client())
    try:
        raw = response(0)
        raw['usage'] = usage
        reply = api.parse(raw)
        assert reply.usage['input_tokens'] == 32
        assert reply.usage['output_tokens'] == expected_output
        assert all(reply.usage[key] == value for key, value in usage.items())
        assert raw['usage'] == usage
        history = History(api, 'Rules', journal, None, image_limit=1)
        history.assistant(reply, [])
        assert history.meter['tokens'] == 151
        # After compaction the meter is reset: opaque reasoning must still
        # contribute to the local estimate, without measuring ciphertext bytes.
        history.meter = None
        estimate = history.local_estimate([])
        api.opaque_reasoning = False
        assert estimate - history.local_estimate([]) == expected_output
    finally:
        api.close()
        journal.close()


def test_grok_normalizes_nested_xai_capabilities(tmp_path):
    journal = Journal(tmp_path)
    api = catalog_provider(journal, [{
        'id': 'grok-4.7', 'input_modalities': ['text', 'image'],
        'capabilities': {'reasoning_effort': ['high', 'xhigh'], 'context_length': 500000},
    }])
    try:
        info = api.check_model()
        assert info['reasoning_efforts'] == ['high', 'xhigh']
        assert info['context_window'] == 500000
    finally:
        api.close()
        journal.close()
