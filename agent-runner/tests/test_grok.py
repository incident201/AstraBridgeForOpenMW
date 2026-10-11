"""Grok uses the same thin, sequential gameplay loop as the other providers."""

import gzip
import json

import httpx
import pytest

from astrabridge_runner.journal import Journal
from astrabridge_runner.providers.grok import Grok
from astrabridge_runner.runner import Runner
from astrabridge_runner.types import ProviderError


KEY = 'xai-fixture-api-key-secret'


class Chunks(httpx.SyncByteStream):
    def __init__(self, data):
        self.data = data

    def __iter__(self):
        # Split both SSE lines and the Unicode text across HTTP chunks.
        for offset in range(0, len(self.data), 7):
            yield self.data[offset:offset + 7]


def response(number, name=None, arguments=None, *, text=''):
    output = [{
        'id': f'reasoning_{number}',
        'type': 'reasoning',
        'summary': [],
        'encrypted_content': f'grok-encrypted-reasoning-{number}',
    }]
    if text:
        output.append({
            'id': f'message_{number}',
            'type': 'message',
            'role': 'assistant',
            'status': 'completed',
            'content': [{'type': 'output_text', 'text': text, 'annotations': []}],
        })
    if name:
        output.append({
            'id': f'function_{number}',
            'type': 'function_call',
            'call_id': f'call_{number}',
            'name': name,
            'arguments': json.dumps(arguments or {}),
            'status': 'completed',
        })
    return {
        'id': f'response_{number}',
        'model': 'grok-4.7',
        'status': 'completed',
        'output': output,
        'usage': {
            'input_tokens': 25000 + number,
            'output_tokens': 100,
            'output_tokens_details': {'reasoning_tokens': 60},
        },
    }


def stream(events):
    data = b': keepalive\r\n\r\n'
    data += b''.join(
        ('event: response\r\ndata: ' + json.dumps(event, ensure_ascii=False) + '\r\n\r\n').encode()
        for event in events
    )
    return httpx.Response(
        200,
        stream=Chunks(data),
        headers={'Content-Type': 'text/event-stream', 'x-request-id': 'xai-fixture-request'},
    )


class Server:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.headers = []

    def handler(self, request):
        assert request.method == 'POST'
        assert request.url.host == 'api.x.ai'
        assert request.url.path == '/v1/responses'
        self.headers.append(request.headers)
        self.requests.append(json.loads(request.content))
        reply = self.replies.pop(0)
        return stream([
            {'type': 'response.output_text.delta', 'delta': 'Наблюдение ✓'},
            {'type': 'response.function_call_arguments.delta', 'delta': '{partial'},
            {'type': 'response.completed', 'response': reply},
        ])

    def provider(self, journal):
        api = Grok(KEY, journal, model='grok-4.7', effort='xhigh', client=httpx.Client(
            base_url='https://api.x.ai/v1/', transport=httpx.MockTransport(self.handler),
        ))
        # Account-specific model discovery is tested separately. The full loop
        # here exercises actual streamed Responses requests and CLI dispatch.
        api.check_model = lambda: {
            'id': 'grok-4.7',
            'name': 'Grok fixture',
            'context_window': 200000,
            'reasoning_efforts': ['xhigh'],
            'raw': {'input_modalities': ['text', 'image']},
        }
        return api


def image_parts(payload):
    return [
        part
        for item in payload['input']
        if isinstance(item.get('content'), list)
        for part in item['content']
        if part['type'] == 'input_image'
    ]


def cli_calls(fixture):
    path = fixture['root'] / 'calls.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def catalog_provider(journal, models, *, model='grok-4.7', effort='xhigh'):
    def handler(request):
        assert request.method == 'GET'
        assert request.url.path == '/v1/language-models'
        assert request.headers['Authorization'] == 'Bearer ' + KEY
        return httpx.Response(200, json={'models': models})

    return Grok(KEY, journal, model=model, effort=effort, client=httpx.Client(
        base_url='https://api.x.ai/v1/', transport=httpx.MockTransport(handler),
    ))


def test_grok_discovers_advertised_47_and_uses_documented_missing_metadata_defaults(fixture):
    api = catalog_provider(fixture['journal'], [{
        'id': 'grok-4.7', 'aliases': [], 'fingerprint': 'fixture',
        'input_modalities': ['text', 'image'],
    }])
    try:
        info = api.check_model()
        assert info['id'] == 'grok-4.7'
        assert info['context_window'] == 500000
        assert info['reasoning_efforts'] == ['low', 'medium', 'high', 'xhigh']
    finally:
        api.close()


def test_grok_catalog_metadata_overrides_documented_defaults(fixture):
    api = catalog_provider(fixture['journal'], [{
        'id': 'grok-4.7', 'input_modalities': ['text', 'image'],
        'context_window': 750000, 'supported_reasoning_efforts': ['high', 'xhigh'],
    }])
    try:
        info = api.check_model()
        assert info['context_window'] == 750000
        assert info['reasoning_efforts'] == ['high', 'xhigh']
    finally:
        api.close()


def test_grok_accepts_only_an_actually_advertised_47_alias(fixture):
    api = catalog_provider(fixture['journal'], [{
        'id': 'grok-4.7-snapshot', 'aliases': ['grok-4.7'],
        'input_modalities': ['text', 'image'], 'context_window': 500000,
    }])
    try:
        info = api.check_model()
        assert info['context_window'] == 500000
        assert api.model == 'grok-4.7'
    finally:
        api.close()


@pytest.mark.parametrize('models, effort', [
    ([{'id': 'grok-4', 'input_modalities': ['text', 'image']}], 'xhigh'),
    ([{'id': 'grok-4.7', 'input_modalities': ['text']}], 'xhigh'),
    ([{'id': 'grok-4.7', 'input_modalities': ['text', 'image']}], 'max'),
    ([{'id': 'grok-4.7', 'input_modalities': ['text', 'image'], 'supported_reasoning_efforts': ['low']}], 'xhigh'),
])
def test_grok_rejects_unavailable_or_incompatible_model_before_game_calls(fixture, models, effort):
    api = catalog_provider(fixture['journal'], models, effort=effort)
    runner = Runner(fixture['skill'], fixture['journal'], api, output=lambda _: None)
    try:
        with pytest.raises(ProviderError):
            runner.prepare()
        assert not any(row['args'][:2] == ['agent', 'connect'] for row in cli_calls(fixture))
        assert not any(row['args'][:1] == ['game'] for row in cli_calls(fixture))
    finally:
        runner.close()


def test_grok_loop_replays_reasoning_full_diagnostics_and_latest_two_images(fixture, monkeypatch):
    monkeypatch.setenv('XAI_API_KEY', KEY)
    monkeypatch.setenv('GROK_API_KEY', KEY)
    server = Server([
        response(0, 'astra_observe', text='Inspecting the environment.'),
        response(1, 'astra_observe'),
        response(2, 'astra_observe'),
        response(3, 'read_skill_reference', {'reference': 'navigation'}),
        response(4, 'astra_act', {'move': 1, 'seconds': .2}),
        response(5, text='Finished the requested task.'),
    ])
    api = server.provider(fixture['journal'])
    runner = Runner(fixture['skill'], fixture['journal'], api, output=lambda _: None)
    try:
        runner.prepare()
        final = runner.turn('Inspect, then move once.')
        assert final.text == 'Finished the requested task.'
        cache_key = server.requests[0]['prompt_cache_key']
        assert isinstance(cache_key, str) and cache_key
        for number, payload in enumerate(server.requests):
            assert payload['model'] == 'grok-4.7'
            assert payload['stream'] is True
            assert payload['store'] is False
            assert payload['parallel_tool_calls'] is False
            assert payload['reasoning'] == {'effort': 'xhigh'}
            assert payload['prompt_cache_key'] == cache_key
            assert 'reasoning.encrypted_content' in payload['include']
            assert 'previous_response_id' not in payload
            assert len(image_parts(payload)) <= 2
            assert all('detail' not in part for part in image_parts(payload))
            assert [
                item['encrypted_content']
                for item in payload['input'] if item.get('type') == 'reasoning'
            ] == [f'grok-encrypted-reasoning-{i}' for i in range(number)]
            assert all(tool['type'] == 'function' for tool in payload['tools'])
            assert all('function' not in tool and 'invocation' not in tool for tool in payload['tools'])
            assert all('namespace' not in tool for tool in payload['tools'])
            exported = {tool['name'] for tool in fixture['tools']['tools']}
            assert {tool['name'] for tool in payload['tools']} == exported | {
                'read_skill_reference', 'view_saved_image',
            }
        assert len(image_parts(server.requests[3])) == 2
        assert image_parts(server.requests[3])[0] != image_parts(server.requests[1])[0]
        outputs = [
            json.loads(item['output'])
            for item in server.requests[-1]['input']
            if item.get('type') == 'function_call_output'
        ]
        movement = next(result for result in outputs if 'action' in result.get('result', {}))
        assert movement['result']['action']['motion'] == {'forward_m': .2}
        assert movement['result']['diagnostics'] == 'do not cut'
        assert movement['result']['feedback']['status'] == 'succeeded'
        assert len([row for row in cli_calls(fixture) if row['args'][:2] == ['game', 'act']]) == 1
        assert not any(row['has_key'] for row in cli_calls(fixture))
        assert all(headers['Authorization'] == 'Bearer ' + KEY for headers in server.headers)
        state = json.loads((fixture['journal'].root / 'active-state.json').read_text())
        assert state['provider'] == 'grok'
        assert state['meter']['usage'] == final.usage
        records = fixture['journal'].records()
        assert any(row['kind'] == 'api_response' and row['usage'] == final.usage for row in records)
        assert cache_key in (fixture['journal'].root / 'manifest.json').read_text()
    finally:
        runner.close()
    # Images remain reconstructable in the archive, while API key values never
    # enter requests, active context, full event records or compressed logs.
    for path in fixture['journal'].root.rglob('*'):
        if path.is_file() and path.suffix in ('.json', '.jsonl', '.gz'):
            text = gzip.open(path, 'rt').read() if path.suffix == '.gz' else path.read_text()
            assert KEY not in text


@pytest.mark.parametrize('terminal', ['response.failed', 'response.incomplete', 'missing', 'malformed'])
def test_grok_never_dispatches_partial_or_failed_streams(fixture, terminal):
    server = Server([])
    api = server.provider(fixture['journal'])
    events = [{
        'type': 'response.output_item.done',
        'output_index': 0,
        'item': response(0, 'astra_act', {'move': 1})['output'][-1],
    }]
    if terminal not in ('missing', 'malformed'):
        events.append({'type': terminal, 'response': {'error': {'message': 'Fixture failure'}}})

    def handler(request):
        if terminal == 'malformed':
            return httpx.Response(200, stream=Chunks(b'data: {not valid JSON}\n\n'))
        return stream(events)

    api.http.client.close()
    api.http.client = httpx.Client(base_url='https://api.x.ai/v1/', transport=httpx.MockTransport(handler))
    runner = Runner(fixture['skill'], fixture['journal'], api, output=lambda _: None)
    try:
        runner.prepare()
        with pytest.raises(ProviderError):
            runner.turn('Move.')
        assert not any(row['args'][:2] == ['game', 'act'] for row in cli_calls(fixture))
        assert (fixture['journal'].root / 'active-state.json').exists()
    finally:
        runner.close()


def test_grok_server_tools_cannot_dispatch_or_hide_a_game_action(fixture):
    malicious = response(0, 'astra_act', {'move': 1})
    malicious['output'].append({'id': 'server_search', 'type': 'web_search_call', 'status': 'completed'})
    runner = Runner(fixture['skill'], fixture['journal'], Server([malicious]).provider(fixture['journal']), output=lambda _: None)
    try:
        runner.prepare()
        with pytest.raises(ProviderError, match='unsupported'):
            runner.turn('Move.')
        assert not any(row['args'][:2] == ['game', 'act'] for row in cli_calls(fixture))
    finally:
        runner.close()


def test_grok_rejects_a_shell_tool_without_providing_shell_access(fixture):
    server = Server([response(0, 'shell', {'command': 'touch should-not-exist'}), response(1, text='Stopped.')])
    runner = Runner(fixture['skill'], fixture['journal'], server.provider(fixture['journal']), output=lambda _: None)
    try:
        runner.prepare()
        runner.turn('Try an unavailable tool.')
        assert 'unknown_tool' in json.dumps(server.requests[-1]['input'])
        assert not (fixture['root'] / 'should-not-exist').exists()
        assert not any(row['args'][:2] == ['game', 'shell'] for row in cli_calls(fixture))
    finally:
        runner.close()


def test_grok_auth_errors_are_redacted_and_not_retried(fixture):
    server = Server([])
    api = server.provider(fixture['journal'])
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(401, json={'error': {'message': 'Invalid key ' + KEY, 'code': 'invalid_api_key'}})

    api.http.client.close()
    api.http.client = httpx.Client(base_url='https://api.x.ai/v1/', transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as caught:
            api.complete('Rules', [], [])
        assert caught.value.status == 401
        assert KEY not in str(caught.value)
        assert len(requests) == 1
        assert requests[0].headers['Authorization'] == 'Bearer ' + KEY
        for path in (fixture['journal'].root / 'api').glob('*.gz'):
            assert KEY not in gzip.open(path, 'rt').read()
    finally:
        api.close()


def test_grok_checkpoint_retains_native_cycles_and_full_history(fixture):
    from test_context_resume import CHECKPOINT

    replies = [response(0, 'astra_observe', text='old_grok_observation ' * 10000)]
    replies.extend(response(number, 'astra_observe') for number in range(1, 13))
    replies[-1]['usage']['input_tokens'] = 160000
    replies.extend([response(13, text=json.dumps(CHECKPOINT)), response(14, text='Done.')])
    server = Server(replies)
    runner = Runner(fixture['skill'], fixture['journal'], server.provider(fixture['journal']), output=lambda _: None)
    try:
        runner.prepare()
        runner.turn('Find the captain')
        events = fixture['journal'].records()
        assert len([row for row in events if row['kind'] == 'context_compacted']) == 1
        state = json.loads((fixture['journal'].root / 'active-state.json').read_text())
        assert state['checkpoint'] == CHECKPOINT
        assert 'old_grok_observation' not in json.dumps(state)
        assert 'old_grok_observation' in (fixture['journal'].root / 'events.jsonl').read_text()
        checkpoint_request = server.requests[13]
        assert 'tools' not in checkpoint_request
        assert checkpoint_request['stream'] and not checkpoint_request['store']
        assert CHECKPOINT['goal'] in json.dumps(server.requests[-1]['input'])
        for cycle in state['cycles']:
            calls = [item['call_id'] for item in cycle['items'] if item.get('type') == 'function_call']
            outputs = [item['call_id'] for item in cycle['items'] if item.get('type') == 'function_call_output']
            assert calls == outputs
    finally:
        runner.close()


def test_grok_resume_preserves_reasoning_and_does_not_repeat_completed_actions(fixture):
    server = Server([response(0, 'astra_observe'), response(1, 'astra_act', {'move': 1, 'seconds': .2}), response(2, text='Paused.')])
    first = Runner(fixture['skill'], fixture['journal'], server.provider(fixture['journal']), output=lambda _: None)
    first.prepare()
    first.turn('Find the captain')
    folder = fixture['journal'].root
    first.close()
    journal = Journal(folder.parent, resume=folder)
    resumed_server = Server([response(3, text='Resumed.')])
    second = Runner(fixture['skill'], journal, resumed_server.provider(journal), output=lambda _: None)
    try:
        second.prepare(resume=True)
        second.continue_turn()
        calls = cli_calls(fixture)
        assert len([row for row in calls if row['args'][:2] == ['game', 'act']]) == 1
        payload = resumed_server.requests[0]
        assert payload['prompt_cache_key'] == server.requests[0]['prompt_cache_key']
        assert [item['encrypted_content'] for item in payload['input'] if item.get('type') == 'reasoning'] == [
            f'grok-encrypted-reasoning-{number}' for number in range(3)
        ]
        assert len(image_parts(payload)) == 1
        assert 'Historical' in json.dumps(payload) or 'historical' in json.dumps(payload)
        assert not any(cycle['pending'] for cycle in second.history.cycles)
    finally:
        second.close()
