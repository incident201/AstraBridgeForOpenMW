"""MiMo wire compatibility and the shared loop, without paid API calls."""

import gzip
import json
from types import SimpleNamespace

import httpx
import pytest

from astrabridge_runner.compaction import Compactor
from astrabridge_runner.journal import Journal
from astrabridge_runner.main import main, provider
from astrabridge_runner.providers.mimo import ChatOutput, MiMo, chat_messages
from astrabridge_runner.runner import Runner
from astrabridge_runner.types import ProviderError
from test_api_loop import call, reply
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
        assert request.url.path == '/v1/chat/completions'
        self.requests.append(json.loads(request.content))
        value = self.replies.pop(0)
        value['model'] = 'mimo-v2.6-pro'
        value['usage'].update(output_tokens_details={'reasoning_tokens': 5})
        delta = {'role': 'assistant', 'reasoning_content': '', 'content': '', 'tool_calls': []}
        for item in value['output']:
            if item['type'] == 'reasoning':
                delta['reasoning_content'] += ''.join(c['text'] for c in item['content'])
            elif item['type'] == 'message':
                delta['content'] += ''.join(c['text'] for c in item['content'])
            else:
                delta['tool_calls'].append({'index': len(delta['tool_calls']),
                    'id': item['call_id'], 'type': 'function',
                    'function': {'name': item['name'], 'arguments': item['arguments']}})
        events = [{'id': value['id'], 'choices': [{'index': 0, 'delta': delta,
            'finish_reason': 'tool_calls' if delta['tool_calls'] else 'stop'}]},
            {'id': value['id'], 'choices': [], 'usage': value['usage']}]
        return httpx.Response(200, text=''.join(
            'data: ' + json.dumps(event) + '\n\n' for event in events
        ))

    def provider(self, journal, effort='high'):
        return MiMo(KEY, journal, effort=effort, client=httpx.Client(
            base_url='https://api.xiaomimimo.com/v1/',
            transport=httpx.MockTransport(self.handler),
        ))


def image_parts(request):
    return [part for message in request['messages'] if isinstance(message.get('content'), list)
            for part in message['content'] if part['type'] == 'image_url']


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
    assert 'detail' not in image_parts(payload)[0]['image_url']
    for request in server.requests:
        assert request['thinking'] == {'type': 'enabled'}
        assert request['stream'] is True
        assert 'store' not in request and 'previous_response_id' not in request
        assert 'parallel_tool_calls' not in request
        assert all(tool['type'] == 'function' and 'function' in tool for tool in request['tools'])
    assistant = next(m for m in server.requests[1]['messages'] if m['role'] == 'assistant')
    assert assistant['reasoning_content'] == 'Full reasoning 0'
    assert assistant['tool_calls'][0]['function']['name'] == 'astra_observe'
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
            assert request['response_format'] == {'type': 'json_object'}
            assert 'tools' not in request
            assert 'pending_actions' in json.dumps(request['messages'])
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
            assert api.payload('rules', [], [])['thinking'] == {'type': 'disabled'}
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
    partial = {'id': 'partial', 'choices': [{'index': 0, 'delta': {'tool_calls': [
        {'index': 0, 'id': 'call', 'type': 'function',
         'function': {'name': 'astra_act', 'arguments': '{"move":1}'}}]}, 'finish_reason': None}]}
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
        with pytest.raises(ProviderError, match='did not finish successfully'):
            runner.turn('Move.')
        calls = [json.loads(line) for line in (fixture['root'] / 'calls.jsonl').read_text().splitlines()]
        assert not any(row['args'][:2] == ['game', 'act'] for row in calls)
    finally:
        runner.close()


def test_mimo_replay_groups_reasoning_commentary_and_calls_without_mutation():
    items = reply(0, [call('astra_observe', {}, 'a'), call('astra_status', {}, 'b')],
                  content='Check the scene and player.')['output']
    items.append({'type': 'function_call_output', 'call_id': 'a', 'output': '{"ok":true}'})
    before = json.dumps(items)
    messages = chat_messages(items)
    assert len(messages) == 2
    assert messages[0]['reasoning_content'] == 'Full reasoning 0'
    assert messages[0]['content'] == 'Check the scene and player.'
    assert len(messages[0]['tool_calls']) == 2
    assert messages[1] == {'role': 'tool', 'tool_call_id': 'a', 'content': '{"ok":true}'}
    assert json.dumps(items) == before


def test_mimo_fragmented_stream_preserves_arguments_and_usage():
    output = ChatOutput()
    def chunk(delta, finish=None):
        return {'id': 'test', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
    output.accept(chunk({'reasoning_content': 'Think ', 'tool_calls': [
        {'index': 0, 'id': 'call1', 'type': 'function', 'function': {'name': 'astra_act', 'arguments': '{"move":'}}]}))
    output.accept(chunk({'reasoning_content': 'again', 'tool_calls': [
        {'index': 0, 'function': {'arguments': '1}'}}]}, 'tool_calls'))
    output.accept({'id': 'test', 'choices': [], 'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
    result = output.finish()
    assert result['output'][0]['content'][0]['text'] == 'Think again'
    assert result['output'][1]['arguments'] == '{"move":1}'
    assert result['usage']['prompt_tokens'] == 100


@pytest.mark.parametrize('finish', [None, 'length', 'content_filter'])
def test_mimo_unsuccessful_stream_never_yields_calls(finish):
    output = ChatOutput()
    output.accept({'choices': [{'index': 0, 'delta': {'tool_calls': [
        {'index': 0, 'id': 'a', 'function': {'name': 'astra_act', 'arguments': '{}'}}]},
        'finish_reason': finish}]})
    with pytest.raises(ProviderError, match='did not finish successfully'):
        output.finish()


def test_mimo_batch_rejection_preserves_actual_results_and_recovers(fixture):
    server = Server([
        reply(0, [call('astra_observe', {}, 'a'), call('astra_act', {'move': 1}, 'b')], content='Check.'),
        reply(1, [call('astra_observe', {}, 'c')]),
        reply(2, [call('astra_act', {'move': 1, 'seconds': .2}, 'd')]),
        reply(3, content='Done.'),
    ])
    runner = Runner(fixture['skill'], fixture['journal'], server.provider(fixture['journal']))
    try:
        runner.prepare()
        runner.turn('Explore.')
        messages = server.requests[1]['messages']
        assert [m['tool_call_id'] for m in messages if m['role'] == 'tool'] == ['a', 'b']
        assert sum('multiple_tool_calls_not_supported' in m.get('content', '')
                   for m in messages if m['role'] == 'tool') == 2
        calls = [json.loads(line) for line in (fixture['root'] / 'calls.jsonl').read_text().splitlines()]
        assert sum(row['args'][:2] == ['game', 'act'] for row in calls) == 1
    finally:
        runner.close()


def test_mimo_retries_temporary_http_error_and_logs_native_usage(tmp_path, monkeypatch):
    journal = Journal(tmp_path)
    server = Server([reply(0, content='Ready.')])
    api = server.provider(journal)
    original = server.handler
    attempts = []
    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(429, headers={'retry-after': '2'}, json={'error': {'message': 'Busy'}})
        return original(request)
    api.http.client.close()
    api.http.client = httpx.Client(base_url='https://api.xiaomimimo.com/v1/',
                                  transport=httpx.MockTransport(handler))
    delays = []
    monkeypatch.setattr('astrabridge_runner.providers.http.time.sleep', delays.append)
    try:
        result = api.complete('rules', [api.user_item('Start.')], [])
        assert result.text == 'Ready.'
        assert delays == [2]
        assert len(attempts) == 2
        assert journal.usage.snapshot()['total']['tokens']['input_tokens'] == 100
        assert journal.usage.snapshot()['by_purpose']['inference']['requests'] == 2
    finally:
        api.close()
        journal.close()


def test_mimo_text_markup_is_never_dispatched(fixture):
    markup = '<tool_call><function=astra_act><parameter=move>1</parameter></function></tool_call>'
    api = Server([reply(0, content=markup)]).provider(fixture['journal'])
    runner = Runner(fixture['skill'], fixture['journal'], api)
    try:
        runner.prepare()
        result = runner.turn('Explore.')
        assert not result.calls
        calls = [json.loads(line) for line in (fixture['root'] / 'calls.jsonl').read_text().splitlines()]
        assert not any(row['args'][:2] == ['game', 'act'] for row in calls)
    finally:
        runner.close()
