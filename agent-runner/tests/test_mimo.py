"""MiMo wire compatibility and the shared loop, without paid API calls."""

import gzip
import json
from types import SimpleNamespace

import httpx
import pytest

from astrabridge_runner.compaction import Compactor
from astrabridge_runner.journal import Journal
from astrabridge_runner.main import main, provider
from astrabridge_runner.providers.mimo import MiMo
from astrabridge_runner.runner import Runner
from astrabridge_runner.types import ProviderError
from test_api_loop import call, image_parts, reply
from test_context_resume import CHECKPOINT


KEY = 'mimo-fixture-secret'


class Server:
    def __init__(self, replies, catalog=None):
        self.replies = list(replies)
        self.catalog = [{'id': 'mimo-v2.6-pro'}] if catalog is None else catalog
        self.requests = []

    def handler(self, request):
        assert request.url.host == 'api.xiaomimimo.com'
        assert request.headers['api-key'] == KEY
        if request.method == 'GET':
            assert request.url.path == '/v1/models'
            return httpx.Response(200, json={'data': self.catalog})
        assert request.url.path == '/v1/responses'
        self.requests.append(json.loads(request.content))
        value = self.replies.pop(0)
        value['model'] = 'mimo-v2.6-pro'
        value['usage'].update(output_tokens_details={'reasoning_tokens': 5})
        events = [
            {'type': 'response.output_item.done', 'output_index': i, 'item': item}
            for i, item in enumerate(value['output'])
        ]
        events.append({'type': 'response.completed', 'response': value})
        return httpx.Response(200, text=''.join(
            'data: ' + json.dumps(event) + '\n\n' for event in events
        ))

    def provider(self, journal, effort='high'):
        return MiMo(KEY, journal, effort=effort, client=httpx.Client(
            base_url='https://api.xiaomimimo.com/v1/',
            transport=httpx.MockTransport(self.handler),
        ))


def test_mimo_cli_loop_and_resume_preserve_reasoning_images_and_diagnostics(fixture, monkeypatch):
    server = Server([
        reply(0, [call('astra_observe', {}, 'view')]),
        reply(1, [call('astra_act', {'move': 1, 'seconds': .2}, 'move')]),
        reply(2, content='Paused.'),
        reply(3, content='Resumed.'),
    ])
    monkeypatch.setenv('MIMO_API_KEY', KEY)
    monkeypatch.setattr('astrabridge_runner.main.MiMo',
                        lambda key, journal, model, effort: server.provider(journal, effort))
    monkeypatch.setattr('builtins.input', lambda _: '/quit')
    sessions = fixture['root'] / 'mimo-sessions'
    assert main(['run', '--provider', 'mimo', '--model', 'mimo-v2.6-pro',
                 '--reasoning', 'high', '--skill', str(fixture['skill']),
                 '--log-dir', str(sessions), '--task', 'Explore.']) == 0
    folder = next(path for path in sessions.iterdir() if path.is_dir())
    assert main(['resume', str(folder), '--task', 'Continue.']) == 0
    payload = server.requests[-1]
    assert 'Full reasoning 0' in json.dumps(payload)
    assert 'Full reasoning 2' in json.dumps(payload)
    assert 'do not cut' in json.dumps(payload)
    assert len(image_parts(payload)) == 1
    assert 'detail' not in image_parts(payload)[0]
    for request in server.requests:
        assert request['reasoning'] == {'effort': 'high'}
        assert request['stream'] is True
        assert 'store' not in request and 'previous_response_id' not in request
        assert 'parallel_tool_calls' not in request
        assert all(tool['type'] == 'function' for tool in request['tools'])
    calls = [json.loads(line) for line in (fixture['root'] / 'calls.jsonl').read_text().splitlines()]
    assert sum(row['args'][:2] == ['game', 'act'] for row in calls) == 1
    assert not any(row['has_key'] for row in calls)
    usage = json.loads((folder / 'usage.json').read_text())['total']['tokens']
    assert usage['input_tokens'] == 406
    assert usage['cached_input_tokens'] == 200
    assert usage['output_tokens'] == 80
    assert usage['reasoning_tokens'] == 20
    for path in folder.rglob('*'):
        if path.suffix in ('.json', '.jsonl', '.gz'):
            text = gzip.open(path, 'rt').read() if path.suffix == '.gz' else path.read_text()
            assert KEY not in text


def test_mimo_checkpoint_json_mode_is_locally_validated(tmp_path):
    server = Server([reply(0, content='{"goal":"missing fields"}'),
                     reply(1, content=json.dumps(CHECKPOINT))])
    journal = Journal(tmp_path)
    api = server.provider(journal)
    try:
        assert Compactor(api, journal).create(
            SimpleNamespace(instructions='rules', payload=lambda: [])
        ) == CHECKPOINT
        assert len(server.requests) == 2
        for request in server.requests:
            assert request['text']['format'] == {'type': 'json_object'}
            assert 'tools' not in request
            assert 'pending_actions' in json.dumps(request['input'])
        assert any(row['kind'] == 'checkpoint_invalid' for row in journal.records())
    finally:
        api.close()
        journal.close()


@pytest.mark.parametrize('catalog,effort,error', [
    ([], 'high', 'not advertised'),
    ([{'id': 'mimo-v2.6-pro', 'input_modalities': ['text']}], 'high', 'image support'),
    ([{'id': 'mimo-v2.6-pro'}], 'invalid', 'reasoning effort'),
])
def test_mimo_rejects_unavailable_capabilities(tmp_path, catalog, effort, error):
    journal = Journal(tmp_path)
    api = Server([], catalog).provider(journal, effort)
    try:
        with pytest.raises(ProviderError, match=error):
            api.check_model()
    finally:
        api.close()
        journal.close()


def test_mimo_catalog_and_key_selection(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('MIMO_API_KEY', raising=False)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'unrelated-key')
    journal = Journal(tmp_path / 'journal')
    try:
        with pytest.raises(ValueError, match='Set MIMO_API_KEY'):
            provider('mimo', journal, SimpleNamespace(), 'mimo-v2.6-pro', 'high')
        monkeypatch.setenv('MIMO_API_KEY', KEY)
        api = provider('mimo', journal, SimpleNamespace(), 'mimo-v2.6-pro', 'none')
        try:
            assert str(api.http.client.base_url) == 'https://api.xiaomimimo.com/v1/'
            assert api.payload('rules', [], [])['reasoning'] == {'effort': 'none'}
        finally:
            api.close()
        monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
        monkeypatch.setattr('astrabridge_runner.main.MiMo',
                            lambda key, journal, model, effort: Server([]).provider(journal))
        assert main(['models', '--provider', 'mimo', '--json']) == 0
        info = json.loads(capsys.readouterr().out)[0]
        assert info['id'] == 'mimo-v2.6-pro'
        assert info['context_window'] == 1_000_000
        assert 'none' in info['reasoning_efforts']
    finally:
        journal.close()


def test_mimo_incomplete_stream_does_not_execute_action(fixture):
    journal = fixture['journal']
    partial = {'type': 'response.output_item.done', 'output_index': 0,
               'item': call('astra_act', {'move': 1})}
    server = Server([])
    api = server.provider(journal)
    original = server.handler

    def handler(request):
        if request.method == 'GET':
            return original(request)
        return httpx.Response(200, text='data: ' + json.dumps(partial) + '\n\n')

    api.http.client.close()
    api.http.client = httpx.Client(base_url='https://api.xiaomimimo.com/v1/',
                                  transport=httpx.MockTransport(handler))
    runner = Runner(fixture['skill'], journal, api)
    try:
        runner.prepare()
        with pytest.raises(ProviderError, match='without response.completed'):
            runner.turn('Move.')
        calls = [json.loads(line) for line in (fixture['root'] / 'calls.jsonl').read_text().splitlines()]
        assert not any(row['args'][:2] == ['game', 'act'] for row in calls)
    finally:
        runner.close()
