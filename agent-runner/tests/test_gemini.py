"""Gemini transport, unchanged native history and the real shared tool loop."""
import base64
import copy
import gzip
import json
from types import SimpleNamespace

import httpx
import pytest
from jsonschema import Draft202012Validator

from astrabridge_runner.compaction import Compactor
from astrabridge_runner.history import History, text_estimate
from astrabridge_runner.journal import Journal
from astrabridge_runner.main import main, provider
from astrabridge_runner.providers.gemini import BASE_URL, Gemini
from astrabridge_runner.runner import Runner
from astrabridge_runner.types import ProviderError, ToolCall


KEY = 'gemini-fixture-secret-key'
MODEL = {'name': 'models/gemini-3.8-flash', 'baseModelId': 'gemini-3.8-flash',
         'displayName': 'Gemini 3.8 Flash', 'inputTokenLimit': 1048576,
         'outputTokenLimit': 65536, 'supportedGenerationMethods': ['generateContent', 'countTokens']}


def response(number, name=None, args=None, text=''):
    steps = [{'type': 'thought', 'signature': f'signed-thought-{number}', 'summary': []}]
    if text:
        steps.append({'type': 'model_output', 'content': [{'type': 'text', 'text': text}]})
    if name:
        steps.append({'type': 'function_call', 'id': f'call_{number}', 'name': name, 'arguments': args or {}})
    return {'id': f'interaction_{number}', 'status': 'requires_action' if name else 'completed', 'steps': steps,
            'usage': {'total_input_tokens': 10000, 'total_output_tokens': 20, 'total_thought_tokens': 22,
                      'total_cached_tokens': 5000, 'total_tokens': 10042}}


class Server:
    def __init__(self, replies, models=None):
        self.replies = list(replies)
        self.models = models if models is not None else [MODEL]
        self.requests = []
        self.headers = []

    def handler(self, request):
        assert request.url.host == 'generativelanguage.googleapis.com'
        assert request.headers['x-goog-api-key'] == KEY
        assert 'key=' not in str(request.url)
        if request.method == 'GET':
            assert request.url.path == '/v1beta/models'
            return httpx.Response(200, json={'models': self.models})
        assert request.method == 'POST' and request.url.path == '/v1beta/interactions'
        self.requests.append(json.loads(request.content))
        self.headers.append(request.headers)
        reply = self.replies.pop(0)
        return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)

    def provider(self, journal, model='gemini-3.8-flash', effort='high'):
        return Gemini(KEY, journal, model, effort, client=httpx.Client(
            base_url=BASE_URL + '/', transport=httpx.MockTransport(self.handler)))


def calls(fixture):
    path = fixture['root'] / 'calls.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def images(payload):
    return [part for item in payload['input'] for part in item.get('content', []) if part['type'] == 'image']


def test_catalog_pagination_and_account_advertised_limits(tmp_path):
    journal = Journal(tmp_path)
    requests = []
    def handler(request):
        requests.append(request)
        assert request.headers['x-goog-api-key'] == KEY
        if len(requests) == 1:
            return httpx.Response(200, json={'models': [], 'nextPageToken': 'page /+? two'})
        assert request.url.params['pageToken'] == 'page /+? two'
        return httpx.Response(200, json={'models': [{**MODEL, 'inputTokenLimit': 987654}]})
    api = Gemini(KEY, journal, client=httpx.Client(base_url=BASE_URL + '/', transport=httpx.MockTransport(handler)))
    try:
        info = api.check_model()
        assert len(requests) == 2 and info['context_window'] == 987654
        assert info['reasoning_efforts'] == ['low', 'medium', 'high']
        assert info['raw']['outputTokenLimit'] == 65536
    finally:
        api.close(); journal.close()


def test_repeated_catalog_page_token_fails_without_infinite_loop(tmp_path):
    journal = Journal(tmp_path)
    api = Gemini(KEY, journal, client=httpx.Client(base_url=BASE_URL + '/', transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={'models': [MODEL], 'nextPageToken': 'same'}))))
    try:
        with pytest.raises(ProviderError, match='repeated'):
            api.models()
        assert journal.api_sequence == 2
    finally:
        api.close(); journal.close()


@pytest.mark.parametrize('models, effort', [
    ([], 'high'), ([MODEL], 'max'), ([MODEL], 'minimal'),
    ([{**MODEL, 'name': 'models/gemini-image', 'baseModelId': 'gemini-image'}], 'high'),
    ([{**MODEL, 'supportedGenerationMethods': ['embedContent']}], 'high'),
])
def test_unsupported_model_or_effort_never_connects_to_game(fixture, models, effort):
    api = Server([], models).provider(fixture['journal'], effort=effort)
    runner = Runner(fixture['skill'], fixture['journal'], api, output=lambda _: None)
    try:
        with pytest.raises(ProviderError):
            runner.prepare()
        assert not any(row['args'][0] == 'game' or row['args'][:2] == ['agent', 'connect'] for row in calls(fixture))
    finally:
        runner.close()


def test_native_definitions_preserve_the_single_source_of_tool_schemas(fixture):
    api = Server([]).provider(fixture['journal'])
    try:
        original = copy.deepcopy(fixture['tools']['tools'])
        converted = api.definitions(original)
        for source, native in zip(original, converted):
            assert native['name'] == source['name']
            assert native['parameters'] is not source['input_schema']
            assert set(native) == {'type', 'name', 'description', 'parameters'}
            Draft202012Validator.check_schema(native['parameters'])
        assert original == fixture['tools']['tools']
    finally:
        api.close()


@pytest.mark.parametrize('name,cases', [
    ('astra_map', [{}, {'action': 'local'}, {'action': 'pan'}, {'action': 'pan', 'dx': 1},
                   {'action': 'pan', 'dx': 'wrong'}, {'action': 'zoom', 'factor': 2},
                   {'action': 'zoom', 'factor': 2, 'fit': True}, {'action': 'local', 'dx': 1}]),
    ('astra_walk', [{}, {'ref': 'ground_1'}, {'ref': 'ground_1', 'x': 1},
                    {'x': 1, 'y': 2, 'observation': 3}, {'x': 1, 'y': 2},
                    {'x': 1.5, 'y': 2, 'observation': 3}]),
])
def test_google_conditional_schema_adaptation_preserves_argument_validation(fixture, name, cases):
    from astrabridge_runner.providers.gemini import parameters
    source = next(tool['input_schema'] for tool in fixture['tools']['tools'] if tool['name'] == name)
    adapted = parameters(source)
    def check(node):
        if isinstance(node, dict):
            assert not set(node.get('required', [])) - set(node.get('properties', {}))
            for value in node.values():check(value)
        elif isinstance(node, list):
            for value in node:check(value)
    check(adapted)
    before, after = Draft202012Validator(source), Draft202012Validator(adapted)
    for args in cases:
        assert before.is_valid(args) == after.is_valid(args), args


def test_schema_conversion_does_not_rewrite_literal_objects_or_weaken_closed_objects():
    from astrabridge_runner.providers.gemini import parameters
    schema = {'type': 'object', 'properties': {'required': {'const': {'required': ['literal']}}}}
    assert parameters(schema) == schema
    with pytest.raises(ProviderError, match='restricted additional properties'):
        parameters({'type': 'object', 'required': ['unknown'], 'additionalProperties': False})


def test_gemini_loop_keeps_signatures_full_results_and_two_recent_screenshots(fixture, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', KEY)
    monkeypatch.setenv('GOOGLE_API_KEY', KEY)
    replies = [response(0, 'astra_observe', text='Осмотр ✓'), response(1, 'astra_observe'),
               response(2, 'astra_observe'), response(3, 'read_skill_reference', {'reference': 'navigation'}),
               response(4, 'astra_act', {'move': 1, 'seconds': .2}), response(5, text='Done.')]
    original = copy.deepcopy(replies)
    server = Server(replies)
    runner = Runner(fixture['skill'], fixture['journal'], server.provider(fixture['journal']), output=lambda _: None)
    root = fixture['journal'].root
    try:
        runner.prepare(); final = runner.turn('Observe, then move once.')
        assert final.text == 'Done.'
        for index, payload in enumerate(server.requests):
            assert payload['model'] == 'gemini-3.8-flash'
            assert payload['store'] is False and payload['stream'] is False
            assert payload['generation_config'] == {'thinking_level': 'high', 'tool_choice': 'auto'}
            assert 'previous_interaction_id' not in payload
            assert len(images(payload)) <= 2
            expected = [step for reply in original[:index] for step in reply['steps']]
            actual = [step for step in payload['input'] if step['type'] in {'thought', 'function_call', 'model_output'}]
            assert actual == expected
            assert all(tool['type'] == 'function' for tool in payload['tools'])
            assert {tool['name'] for tool in payload['tools']} == {tool['name'] for tool in fixture['tools']['tools']} | {
                'view_saved_image', 'read_skill_reference'}
        assert len(images(server.requests[3])) == 2
        assert images(server.requests[3])[0] != images(server.requests[1])[0]
        assert images(server.requests[1])[0]['mime_type'] == 'image/png'
        assert base64.b64decode(images(server.requests[1])[0]['data']).startswith(b'\x89PNG')
        results = [item['result'] for item in server.requests[-1]['input'] if item['type'] == 'function_result']
        movement = next(row for row in results if row.get('result', {}).get('diagnostics') == 'do not cut')
        assert movement['result']['action']['motion']['forward_m'] == .2
        assert movement['result']['feedback']['status'] == 'succeeded'
        assert sum(row['args'][:2] == ['game', 'act'] for row in calls(fixture)) == 1
        assert not any(row['has_key'] for row in calls(fixture))
        assert len(runner.resources.images) == 3
        assert final.usage['input_tokens'] == 10000 and final.usage['output_tokens'] == 42
        assert final.usage['total_cached_tokens'] == 5000
        for index, payload in enumerate(server.requests, 2):  # API call 1 is discovery.
            record = fixture['journal'].read_api_record(f'api/{index:06}-request.json.gz')
            assert record['body'] == payload
    finally:
        runner.close()
    for path in root.rglob('*'):
        if path.is_file() and path.suffix in {'.json', '.jsonl', '.gz'}:
            text = gzip.open(path, 'rt').read() if path.suffix == '.gz' else path.read_text()
            assert KEY not in text


@pytest.mark.parametrize('status', ['incomplete', 'failed', 'in_progress', 'cancelled', 'queued'])
def test_incomplete_or_failed_response_cannot_execute_tools(fixture, status):
    raw = response(0, 'astra_act', {'move': 1})
    raw['status'] = status
    runner = Runner(fixture['skill'], fixture['journal'], Server([raw]).provider(fixture['journal']), output=lambda _: None)
    try:
        runner.prepare()
        with pytest.raises(ProviderError, match='did not complete'):
            runner.turn('Move')
        assert not any(row['args'][:2] == ['game', 'act'] for row in calls(fixture))
    finally:
        runner.close()


def test_batches_are_rejected_before_any_game_action(fixture):
    raw = response(0, 'astra_act', {'move': 1})
    raw['steps'].append({'type': 'function_call', 'id': 'other', 'name': 'astra_act', 'arguments': {'move': -1}})
    server = Server([raw, response(1, text='I will make one call at a time.')])
    runner = Runner(fixture['skill'], fixture['journal'], server.provider(fixture['journal']), output=lambda _: None)
    try:
        runner.prepare(); runner.turn('Move')
        assert not any(row['args'][:2] == ['game', 'act'] for row in calls(fixture))
        results = [step for step in server.requests[-1]['input'] if step['type'] == 'function_result']
        assert len(results) == 2 and all(row['is_error'] for row in results)
        assert all(row['result']['error'] == 'multiple_tool_calls_not_supported' for row in results)
    finally:
        runner.close()


@pytest.mark.parametrize('change', ['duplicate', 'string_args', 'missing_name', 'search', 'bad_usage', 'nan', 'no_calls'])
def test_malformed_or_unsupported_steps_fail_before_dispatch(tmp_path, change):
    journal = Journal(tmp_path); api = Server([]).provider(journal)
    raw = response(0, 'astra_act')
    if change == 'duplicate': raw['steps'].append(copy.deepcopy(raw['steps'][-1]))
    elif change == 'string_args': raw['steps'][-1]['arguments'] = '{}'
    elif change == 'missing_name': raw['steps'][-1].pop('name')
    elif change == 'search': raw['steps'].append({'type': 'google_search_call', 'id': 'search'})
    elif change == 'bad_usage': raw['usage']['total_input_tokens'] = '100'
    elif change == 'nan': raw['steps'][-1]['arguments'] = {'move': float('nan')}
    elif change == 'no_calls': raw['steps'] = raw['steps'][:1]
    try:
        with pytest.raises(ProviderError): api.parse(raw)
    finally:
        api.close(); journal.close()


def test_checkpoint_request_has_no_tools_and_keeps_native_history(fixture):
    checkpoint = {'goal': 'Find the observed door', **{key: [] for key in (
        'plan', 'facts', 'uncertainties', 'failed_attempts', 'pending_actions', 'references')}}
    server = Server([response(1, text=json.dumps(checkpoint))])
    api = server.provider(fixture['journal'])
    history = History(api, 'Game rules', fixture['journal'], None)
    history.user('Find the door')
    previous = response(0, 'astra_observe')
    history.assistant(api.parse(previous), [])
    history.tool(ToolCall('call_0', 'astra_observe', '{}'), {'ok': True, 'result': {'location': 'Room'}})
    try:
        assert Compactor(api, fixture['journal']).create(history) == checkpoint
        payload = server.requests[0]
        assert 'tools' not in payload and payload['generation_config']['tool_choice'] == 'none'
        assert previous['steps'][0] in payload['input']
        assert history.checkpoint is None, 'creating a checkpoint does not itself discard active history'
    finally:
        api.close()


def test_thought_signature_is_preserved_but_not_counted_as_plain_text(fixture):
    api = Server([]).provider(fixture['journal'])
    raw = response(0, text='Done')
    raw['steps'][0]['signature'] = 'opaque' * 100000
    try:
        parsed = api.parse(raw)
        assert parsed.native == raw['steps'] and parsed.native is not raw['steps']
        assert text_estimate(parsed.native) < 100
        history = History(api, 'Rules', fixture['journal'], None, image_limit=1)
        history.assistant(parsed, [])
        assert history.meter['tokens'] == 10042
        history.meter = None; before = history.local_estimate([])
        api.opaque_reasoning = False
        assert before - history.local_estimate([]) == 42
    finally:
        api.close()


def test_text_parts_are_joined_without_changing_json_string_contents(tmp_path):
    journal = Journal(tmp_path); api = Server([]).provider(journal)
    raw = response(0, text='unused')
    raw['steps'][-1]['content'] = [{'type': 'text', 'text': '{"goal":"Reach'},
                                  {'type': 'text', 'text': ' the door"}'}]
    try:
        assert json.loads(api.parse(raw).text) == {'goal': 'Reach the door'}
    finally:
        api.close(); journal.close()


def test_cli_key_selection_discovery_and_resume(fixture, monkeypatch, capsys):
    monkeypatch.setenv('GEMINI_API_KEY', KEY)
    server = Server([response(0, 'astra_observe'), response(1, text='First task done.'),
                     response(2, 'astra_act', {'move': 1, 'seconds': .2}), response(3, text='Second task done.')])
    monkeypatch.setattr('astrabridge_runner.main.Gemini', lambda key, journal, model, effort:
                        server.provider(journal, model, effort))
    monkeypatch.setattr('builtins.input', lambda _: '/quit')
    monkeypatch.setenv('XDG_STATE_HOME', str(fixture['root']))
    assert main(['models', '--provider', 'gemini', '--json']) == 0
    assert json.loads(capsys.readouterr().out)[0]['id'] == 'gemini-3.8-flash'
    logs = fixture['root'] / 'gemini-sessions'
    assert main(['run', '--provider', 'gemini', '--model', 'gemini-3.8-flash', '--reasoning', 'high',
                 '--skill', str(fixture['skill']), '--log-dir', str(logs), '--task', 'First task']) == 0
    folder = next(path for path in logs.iterdir() if path.is_dir())
    assert main(['resume', str(folder), '--task', 'Second task']) == 0
    payload = json.dumps(server.requests[-1])
    assert 'First task' in payload and 'Second task' in payload and 'signed-thought-0' in payload
    assert sum(row['args'][:2] == ['game', 'act'] for row in calls(fixture)) == 1
    assert not any(row['has_key'] for row in calls(fixture))


def test_missing_key_does_not_use_another_provider_key(tmp_path, monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'unrelated-key')
    journal = Journal(tmp_path)
    try:
        with pytest.raises(ValueError, match='Set GEMINI_API_KEY'):
            provider('gemini', journal, SimpleNamespace(), 'gemini-3.8-flash', 'high')
    finally:
        journal.close()


def test_retries_use_the_same_native_request_and_permanent_errors_stop(tmp_path, monkeypatch):
    monkeypatch.setattr('astrabridge_runner.providers.http.time.sleep', lambda _: None)
    journal = Journal(tmp_path)
    server = Server([httpx.Response(429, json={'error': {'code': 429}}, headers={'Retry-After': '2'}),
                     response(0, text='Done')])
    api = server.provider(journal)
    try:
        assert api.complete('Rules', [], []).text == 'Done'
        assert len(server.requests) == 2 and server.requests[0] == server.requests[1]
        server.replies = [httpx.Response(400, json={'error': {'message': KEY, 'code': 400}})]
        with pytest.raises(ProviderError) as failure: api.complete('Rules', [], [])
        assert KEY not in str(failure.value)
        assert len(server.requests) == 3
        assert KEY not in (journal.root / 'events.jsonl').read_text()
    finally:
        api.close(); journal.close()


def test_compaction_keeps_recent_complete_cycles_and_can_continue_playing(fixture):
    checkpoint = {'goal': 'Reach the door', **{key: [] for key in (
        'plan', 'facts', 'uncertainties', 'failed_attempts', 'pending_actions', 'references')}}
    server = Server([response(20, text=json.dumps(checkpoint)),
                     response(21, 'astra_act', {'move': 1, 'seconds': .2}), response(22, text='Done')])
    api = server.provider(fixture['journal'])
    runner = Runner(fixture['skill'], fixture['journal'], api, context_window=100000, output=lambda _: None)
    try:
        runner.prepare(); runner.history.user('Reach the door')
        for number in range(10):
            raw = response(number, text=('old_observation ' * 30000) if number == 0 else f'Recent observation {number}')
            raw['usage'].update(total_input_tokens=90000, total_tokens=90042)
            parsed = api.parse(raw)
            fixture['journal'].event('assistant', native=parsed.native)
            runner.history.assistant(parsed, [])
        runner.continue_turn()
        assert runner.history.checkpoint == checkpoint
        active = json.dumps(runner.history.snapshot())
        assert 'old_observation' not in active and 'old_observation' in (fixture['journal'].root/'events.jsonl').read_text()
        assert 'signed-thought-2' in active and 'signed-thought-0' not in active
        assert server.requests[0]['generation_config']['tool_choice'] == 'none'
        assert server.requests[1]['generation_config']['tool_choice'] == 'auto'
        assert 'Historical model-generated checkpoint' in json.dumps(server.requests[1])
        assert sum(row['args'][:2] == ['game', 'act'] for row in calls(fixture)) == 1
    finally:
        runner.close()


def test_resume_recovers_unknown_call_without_executing_it_again(fixture):
    first_server = Server([])
    api = first_server.provider(fixture['journal'])
    runner = Runner(fixture['skill'], fixture['journal'], api, output=lambda _: None)
    root = fixture['journal'].root
    runner.prepare(); runner.history.user('Move once')
    parsed = api.parse(response(0, 'astra_act', {'move': 1, 'seconds': .2}))
    runner.history.assistant(parsed, [{'call': parsed.calls[0].dump(), 'execution_id': 'interrupted'}])
    fixture['journal'].event('tool_start', execution_id='interrupted', request_id='uncertain-request')
    runner.close()
    journal = Journal(root.parent, resume=root)
    server = Server([response(1, text='The previous action is uncertain; inspect its receipt.')])
    resumed = Runner(fixture['skill'], journal, server.provider(journal), output=lambda _: None)
    try:
        resumed.prepare(resume=True); resumed.continue_turn()
        assert not any(row['args'][:2] == ['game', 'act'] for row in calls(fixture))
        result = next(step for step in server.requests[-1]['input'] if step['type'] == 'function_result')
        assert result['call_id'] == 'call_0' and result['result']['result_unknown'] is True
        assert result['result']['request_id'] == 'uncertain-request'
        assert 'signed-thought-0' in json.dumps(server.requests[-1])
    finally:
        resumed.close()


def test_empty_model_output_is_not_success_and_missing_usage_is_not_invented(tmp_path):
    journal = Journal(tmp_path); api = Server([]).provider(journal)
    try:
        raw = response(0, text='unused')
        for parts in ([], [{'type': 'text', 'text': ''}], [{'type': 'text', 'text': '  '} ]):
            raw['steps'][-1]['content'] = parts
            with pytest.raises(ProviderError, match='neither tool calls nor visible text'):
                api.parse(raw)
        raw = response(1, text='Done');raw.pop('usage')
        assert api.parse(raw).usage == {}
    finally:
        api.close();journal.close()
