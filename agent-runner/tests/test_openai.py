import gzip
import json

import httpx
import pytest

from astrabridge_runner.providers.openai import OpenAI
from astrabridge_runner.runner import Runner
from astrabridge_runner.types import ProviderError


class Auth:
    directory = '/fixture/auth'
    def __init__(self): self.refreshes = 0
    def resolve(self, account=None): return {'id': account or 'registration'}
    def access(self, account=None, force=False):
        self.refreshes += bool(force); return 'oauth-access-secret'
    def close(self): pass


class Chunks(httpx.SyncByteStream):
    def __init__(self, data, *, interrupt=False): self.data, self.interrupt = data, interrupt
    def __iter__(self):
        for i in range(0, len(self.data), 13):
            yield self.data[i:i+13]
        if self.interrupt: raise KeyboardInterrupt()


def response(n, name=None, args=None, *, text='', namespace='astrabridge'):
    items = [{'id': f'rs_{n}', 'type': 'reasoning', 'summary': [], 'encrypted_content': f'encrypted_reasoning_{n}'}]
    if text: items.append({'id': f'msg_{n}', 'type': 'message', 'role': 'assistant', 'phase': 'commentary' if name else 'final_answer',
                           'status': 'completed', 'content': [{'type': 'output_text', 'text': text, 'annotations': []}]})
    if name: items.append({'id': f'fc_{n}', 'type': 'function_call', 'call_id': f'call_{n}', 'name': name, 'namespace': namespace,
                           'arguments': json.dumps(args or {}), 'status': 'completed'})
    return {'id': f'resp_{n}', 'status': 'completed', 'output': items, 'model': 'gpt-fixture',
            'usage': {'input_tokens': 25000+n, 'output_tokens': 100, 'output_tokens_details': {'reasoning_tokens': 60}}}


class Server:
    def __init__(self, replies): self.replies = replies; self.requests = []; self.failure = None; self.interrupt = False
    def handler(self, request):
        if request.method == 'GET':
            assert request.url.path == '/v1/models'
            return httpx.Response(200, json={'models': [
                {'slug': 'hidden', 'visibility': 'hidden'},
                {'slug': 'gpt-fixture', 'display_name': 'Fixture GPT', 'visibility': 'list', 'context_window': 1048576,
                 'input_modalities': ['text', 'image'], 'supported_reasoning_efforts': ['xhigh']}]})
        assert request.url.path == '/v1/responses'
        payload = json.loads(request.content); self.requests.append(payload)
        if self.failure: return httpx.Response(self.failure[0], json=self.failure[1])
        reply = self.replies.pop(0)
        events = [{'type': 'response.output_text.delta', 'delta': 'Текст ✓'},
                  {'type': 'response.function_call_arguments.delta', 'delta': '{partial'},
                  {'type': 'response.completed', 'response': reply}]
        data = b': heartbeat\r\n\r\n' + b''.join(('event: response\r\ndata: ' + json.dumps(e, ensure_ascii=False) + '\r\n\r\n').encode() for e in events)
        if self.interrupt: data = ('data: '+json.dumps(events[0])+'\n\n').encode()
        return httpx.Response(200, stream=Chunks(data, interrupt=self.interrupt), headers={'Content-Type': 'text/event-stream', 'x-request-id': 'request-fixture'})
    def provider(self, journal):
        return OpenAI(Auth(), journal, 'gpt-fixture', 'xhigh', client=httpx.Client(base_url='https://api.openai.com/v1/', transport=httpx.MockTransport(self.handler)))


def images(payload):
    return [part for item in payload['input'] if isinstance(item.get('content'), list) for part in item['content'] if part['type'] == 'input_image']


def test_responses_loop_keeps_native_reasoning_phase_and_two_images(fixture):
    f = fixture; server = Server([response(0, 'astra_observe', text='Looking now.'), response(1, 'astra_observe'), response(2, 'astra_observe'),
        response(3, 'read_skill_reference', {'reference': 'navigation'}, namespace='runner'),
        response(4, 'astra_act', {'move': 1, 'seconds': .2}), response(5, text='Goal complete.')])
    api = server.provider(f['journal']); runner = Runner(f['skill'], f['journal'], api)
    try:
        runner.prepare(); runner.turn('A new goal.')
        for n, body in enumerate(server.requests):
            assert body['store'] is False and body['stream'] is True and body['parallel_tool_calls'] is False
            assert body['reasoning'] == {'effort': 'xhigh'}
            assert set(body).isdisjoint({'previous_response_id', 'max_output_tokens', 'temperature', 'conversation', 'metadata', 'truncation'})
            assert len(images(body)) <= 2
            assert all(item.get('role') != 'system' for item in body['input'])
            assert [item['encrypted_content'] for item in body['input'] if item.get('type') == 'reasoning'] == [f'encrypted_reasoning_{i}' for i in range(n)]
            assert all(namespace['type'] == 'namespace' for namespace in body['tools'])
            assert all('invocation' not in tool for namespace in body['tools'] for tool in namespace['tools'])
        assert len(images(server.requests[3])) == 2
        assert images(server.requests[3])[0] != images(server.requests[1])[0]
        final = json.dumps(server.requests[-1]['input'])
        assert 'motion' in final and 'diagnostics' in final and 'succeeded' in final
        assert 'phase' in final
    finally: runner.close()
    for path in (f['journal'].root/'api').glob('*.gz'):
        assert 'oauth-access-secret' not in gzip.open(path, 'rt').read()


@pytest.mark.parametrize('terminal', ['response.failed', 'response.incomplete', 'missing'])
def test_no_game_action_before_completed_terminal_event(fixture, terminal):
    f = fixture; server = Server([]); api = server.provider(f['journal'])
    def handler(request):
        if request.method == 'GET': return server.handler(request)
        item = {'type': 'response.output_item.done', 'output_index': 0, 'item': response(0, 'astra_act')['output'][-1]}
        events = [item]
        if terminal != 'missing': events.append({'type': terminal, 'response': {'error': {'code': 'subscription_sharing_usage_limit_exceeded'}}})
        data = b''.join(('data: '+json.dumps(e)+'\n\n').encode() for e in events)
        return httpx.Response(200, stream=Chunks(data))
    api.http.client.close(); api.http.client = httpx.Client(base_url='https://api.openai.com/v1/', transport=httpx.MockTransport(handler))
    runner = Runner(f['skill'], f['journal'], api)
    try:
        runner.prepare()
        with pytest.raises(ProviderError): runner.turn('Move.')
        calls = [json.loads(row) for row in (f['root']/'calls.jsonl').read_text().splitlines()]
        assert not any(call['args'][:2] == ['game', 'act'] for call in calls)
        assert 'response.output_item.done' in gzip.open(sorted((f['journal'].root/'api').glob('*response*'))[-1], 'rt').read()
    finally: runner.close()


@pytest.mark.parametrize('code', ['subscription_sharing_usage_limit_exceeded', 'subscription_sharing_usage_unavailable'])
def test_subscription_limit_is_not_retried_or_billed_with_api_key(fixture, monkeypatch, code):
    server = Server([]); server.failure = (429, {'error': {'code': code, 'message': 'App limit'}})
    monkeypatch.setenv('OPENAI_API_KEY', 'forbidden-api-balance')
    api = server.provider(fixture['journal'])
    try:
        with pytest.raises(ProviderError) as error: api.complete('Rules', [], [])
        assert error.value.code == code and len(server.requests) == 1
    finally: api.close()


def test_interrupted_stream_retains_partial_events(fixture):
    server = Server([response(0)]); server.interrupt = True; api = server.provider(fixture['journal'])
    try:
        with pytest.raises(KeyboardInterrupt): api.complete('Rules', [], [])
        body = json.loads(gzip.open(next((fixture['journal'].root/'api').glob('*response*')), 'rt').read())
        assert body['body']['events'][0]['type'] == 'response.output_text.delta'
    finally: api.close()


def test_unknown_namespace_does_not_execute_tools(fixture):
    server = Server([response(0, 'astra_act', {'move': 1}, namespace='shell'), response(1)])
    runner = Runner(fixture['skill'], fixture['journal'], server.provider(fixture['journal']))
    try:
        runner.prepare(); runner.turn('Test')
        assert 'unknown_tool_namespace' in json.dumps(server.requests[-1])
        assert not any(json.loads(row)['args'][:2] == ['game', 'act'] for row in (fixture['root']/'calls.jsonl').read_text().splitlines())
    finally: runner.close()


def test_openai_json_checkpoint_replaces_only_active_native_context(fixture):
    from test_context_resume import CHECKPOINT
    f = fixture
    replies = [response(0, 'astra_observe', text='old_visual_observation ' * 10000)]
    replies.extend(response(n, 'astra_observe') for n in range(1, 13))
    replies[-1]['usage']['input_tokens'] = 160000
    replies.extend([response(13, text=json.dumps(CHECKPOINT)), response(14, text='Finished.')])
    server = Server(replies)
    runner = Runner(f['skill'], f['journal'], server.provider(f['journal']), context_window=200000, output=lambda _: None)
    try:
        runner.prepare(); runner.turn('Find the captain')
        compacted = [row for row in f['journal'].records() if row['kind'] == 'context_compacted']
        assert len(compacted) == 1
        active = json.loads((f['journal'].root/'active-state.json').read_text())
        assert active['checkpoint'] == CHECKPOINT
        assert 'old_visual_observation' not in json.dumps(active)
        assert 'old_visual_observation' in (f['journal'].root/'events.jsonl').read_text()
        summary = server.requests[13]
        assert 'tools' not in summary and summary['stream'] and not summary['store']
        assert CHECKPOINT['goal'] in json.dumps(server.requests[-1])
        # All retained function calls still have exactly one output, with their
        # encrypted reasoning and message phases preserved in their cycles.
        for cycle in active['cycles']:
            ids = [item['call_id'] for item in cycle['items'] if item.get('type') == 'function_call']
            outputs = [item['call_id'] for item in cycle['items'] if item.get('type') == 'function_call_output']
            assert ids == outputs
    finally: runner.close()


def test_empty_terminal_output_uses_completed_native_stream_items(fixture):
    f = fixture; server = Server([]); api = server.provider(f['journal'])
    native = response(0, 'astra_observe', text='Inspecting the game.')
    def handler(request):
        events = []
        for index, item in enumerate(native['output']):
            events.extend([{'type': 'response.output_item.added', 'output_index': index, 'item': {**item, 'status': 'in_progress'}},
                           {'type': 'response.output_item.done', 'output_index': index, 'item': item}])
        terminal = {**native, 'output': []}
        events.append({'type': 'response.completed', 'response': terminal})
        return httpx.Response(200, stream=Chunks(b''.join(('data: '+json.dumps(e)+'\n\n').encode() for e in events)))
    api.http.client.close(); api.http.client = httpx.Client(base_url='https://api.openai.com/v1/', transport=httpx.MockTransport(handler))
    try:
        reply = api.complete('Rules', [api.user_item('Observe')], [])
        assert reply.native == native['output']
        assert reply.text == 'Inspecting the game.' and reply.calls[0].name == 'astra_observe'
        assert reply.native[0]['encrypted_content'] == 'encrypted_reasoning_0'
        assert reply.native[1]['phase'] == 'commentary'
    finally: api.close()


def test_terminal_completion_cannot_hide_unfinished_stream_item(fixture):
    api = Server([]).provider(fixture['journal'])
    events = [{'type': 'response.output_item.added', 'output_index': 0, 'item': response(0, 'astra_act')['output'][-1]},
              {'type': 'response.completed', 'response': {**response(0), 'output': []}}]
    api.http.client.close(); api.http.client = httpx.Client(base_url='https://api.openai.com/v1/', transport=httpx.MockTransport(
        lambda _: httpx.Response(200, stream=Chunks(b''.join(('data: '+json.dumps(e)+'\n\n').encode() for e in events)))))
    try:
        with pytest.raises(ProviderError, match='no completed output'): api.complete('Rules', [], [])
    finally: api.close()


def test_subscription_catalog_reasoning_levels_use_advertised_effort_values():
    from astrabridge_runner.types import model_info
    info = model_info({'slug': 'gpt-6-luna', 'supported_reasoning_levels': [
        {'effort': 'low', 'description': 'Light reasoning'}, {'effort': 'max', 'description': 'Maximum reasoning'}]}, 'openai')
    assert info['reasoning_efforts'] == ['low', 'max']
