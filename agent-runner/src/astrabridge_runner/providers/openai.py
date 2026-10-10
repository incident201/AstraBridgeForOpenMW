import copy
import json

import httpx

from .http import RETRY_STATUSES, Transport
from ..journal import json_text
from ..types import ProviderError, Reply, ToolCall, model_info


def sse(lines):
    """HTTPX decodes incremental UTF-8; SSE data can span multiple lines."""
    data = []
    for line in lines:
        if not line:
            if data:
                value = '\n'.join(data); data = []
                if value != '[DONE]': yield json.loads(value)
        elif line.startswith('data:'):
            data.append(line[5:].lstrip(' '))
    if data and '\n'.join(data) != '[DONE]': yield json.loads('\n'.join(data))


class OpenAI:
    name = 'openai'
    streamed = True

    def __init__(self, auth, journal, model, effort, *, account=None, client=None):
        self.auth, self.journal, self.model, self.effort = auth, journal, model, effort
        self.account = auth.resolve(account)['id']
        self.http = Transport(journal, 'https://api.openai.com/v1', client)

    def headers(self, force=False):
        token = self.auth.access(self.account, force=force); self.journal.add_secret(token)
        return {'Authorization': 'Bearer ' + token}

    def models(self):
        try: data = self.http.request('GET', 'models', headers=self.headers())
        except ProviderError as exc:
            if exc.status != 401: raise
            data = self.http.request('GET', 'models', headers=self.headers(True))
        return [model_info(item, self.name) for item in data.get('models', []) if item.get('visibility') == 'list']

    def check_model(self):
        info = next((item for item in self.models() if item['id'] == self.model), None)
        if not info: raise ProviderError('The requested GPT model is not available to the selected ChatGPT account.')
        modalities = info['raw'].get('input_modalities')
        if modalities and 'image' not in modalities: raise ProviderError('This GPT model does not accept screenshots.')
        if info['reasoning_efforts'] and self.effort not in info['reasoning_efforts']: raise ProviderError('This GPT model does not support the selected reasoning effort.')
        return info

    def definitions(self, tools):
        groups = {'astrabridge': [], 'runner': []}
        for tool in tools:
            namespace = 'astrabridge' if tool['name'].startswith('astra_') else 'runner'
            groups[namespace].append({'type': 'function', 'name': tool['name'], 'description': tool['description'],
                                      'parameters': tool['input_schema'], 'strict': False})
        return [{'type': 'namespace', 'name': name, 'description': 'AstraBridge gameplay tools.' if name == 'astrabridge' else 'Read exported skill references and archived game images.',
                 'tools': functions} for name, functions in groups.items() if functions]

    def user_item(self, text): return {'role': 'user', 'content': [{'type': 'input_text', 'text': text}]}
    def tool_item(self, call, result): return {'type': 'function_call_output', 'call_id': call.id, 'output': json_text(result)}
    def image_item(self, ref, caption): return {'role': 'user', 'content': [{'type': 'input_text', 'text': caption}, {'type': 'saved_image', 'image_ref': ref}]}
    def image_content(self, resources, ref):
        value = resources.content(ref)
        return {'type': 'input_image', 'image_url': value['image_url']['url'], 'detail': 'auto'}

    def complete(self, instructions, items, tools, *, checkpoint=False, on_text=None):
        payload = {'model': self.model, 'instructions': instructions, 'input': items, 'store': False, 'stream': True,
                   'reasoning': {'effort': self.effort}, 'parallel_tool_calls': False}
        if tools: payload.update(tools=self.definitions(tools), tool_choice='none' if checkpoint else 'auto')
        refreshed = False
        for attempt in range(3):
            index, start = self.http.begin('POST', 'responses', payload, attempt)
            events = []; status = None; headers = {}; completed = None
            done_items = {}; added_indices = set()
            try:
                with self.http.client.stream('POST', 'responses', json=payload, headers=self.headers()) as response:
                    status, headers = response.status_code, response.headers
                    if not response.is_success:
                        response.read()
                        try: body = response.json()
                        except ValueError: body = {'detail': response.text}
                        self.http.finish(index, start, status, headers, body)
                        error = body.get('error', {}) if isinstance(body, dict) else {}
                        code = error.get('code') if isinstance(error, dict) else None
                        if not isinstance(code, str): code = None
                        if status == 401 and not refreshed:
                            self.headers(True); refreshed = True; continue
                        retryable = status in RETRY_STATUSES and not (code or '').startswith('subscription_sharing_')
                        if retryable and attempt < 2 and self.http.wait_to_retry(attempt, headers):
                            continue
                        raise ProviderError(f'OpenAI returned HTTP {status}: ' + self.journal.clean(json_text(body)), code=code, status=status)
                    for event in sse(response.iter_lines()):
                        events.append(event)
                        self.journal.event('stream_event',index=index,event=event)
                        kind = event.get('type')
                        if kind in ('response.output_item.added', 'response.output_item.done'):
                            position = event.get('output_index')
                            if type(position) is not int or position < 0 or not isinstance(event.get('item'), dict):
                                raise ProviderError('Malformed OpenAI output-item event.')
                            added_indices.add(position)
                            if kind == 'response.output_item.done':
                                if position in done_items and done_items[position] != event['item']:
                                    raise ProviderError('OpenAI emitted conflicting completed output items.')
                                done_items[position] = copy.deepcopy(event['item'])
                        if kind == 'response.output_text.delta' and on_text and not checkpoint: on_text(event.get('delta', ''))
                        if kind in ('response.failed', 'response.incomplete', 'error'):
                            error = event.get('response', {}).get('error') or event.get('error') or {}
                            if not isinstance(error, dict): error = {'message': str(error)}
                            raise ProviderError('OpenAI stream failed: ' + json_text(event), code=error.get('code'), status=status)
                        if kind == 'response.completed':
                            if completed is not None: raise ProviderError('OpenAI emitted duplicate completion events.')
                            completed = event['response']
                if completed is None: raise ProviderError('OpenAI stream ended without response.completed. No tools were executed.')
                # The subscription route can leave response.completed.output
                # empty. Completed item events are the full native replay data,
                # including message phase and encrypted reasoning; never build
                # tool calls from argument deltas or execute before completion.
                if done_items:
                    if added_indices != set(done_items) or sorted(done_items) != list(range(len(done_items))):
                        raise ProviderError('OpenAI stream contains unfinished output items. No tools were executed.')
                    if completed.get('output') and len(completed['output']) != len(done_items):
                        raise ProviderError('OpenAI terminal output disagrees with the completed stream items. No tools were executed.')
                    completed = copy.deepcopy(completed)
                    completed['output'] = [done_items[i] for i in sorted(done_items)]
                elif added_indices:
                    raise ProviderError('OpenAI stream contains no completed output items. No tools were executed.')
            except BaseException as exc:
                if status is None and isinstance(exc,httpx.TransportError) and attempt < 2:
                    self.http.finish(index, start, status, headers, {'transport_error': str(exc)})
                    self.http.wait_to_retry(attempt, {})
                    continue
                if status is None or status < 400:
                    self.http.finish(index, start, status, headers, {'events': events, 'error': str(exc)})
                if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
                raise ProviderError(self.journal.clean(str(exc)), code=getattr(exc, 'code', None), status=status) from exc
            self.http.finish(index, start, status, headers, {'events': events, **completed})
            return self.parse(completed)
        raise ProviderError('OpenAI retries exhausted.')

    def parse(self, response):
        if response.get('status') != 'completed': raise ProviderError('OpenAI returned an incomplete final response.')
        native = response.get('output')
        if not isinstance(native, list): raise ProviderError('OpenAI returned no output items.')
        calls = []; text = []
        for item in native:
            if item.get('type') == 'function_call':
                if item.get('status') in ('in_progress','incomplete'):raise ProviderError('OpenAI returned an unfinished function call.')
                if any(not isinstance(item.get(k), str) for k in ('call_id', 'name', 'arguments')): raise ProviderError('Malformed OpenAI function call.')
                namespace = item.get('namespace'); name = item['name']
                if '.' in name:
                    prefix, name = name.split('.', 1)
                    if namespace and namespace != prefix: raise ProviderError('Conflicting tool namespaces.')
                    namespace = prefix
                calls.append(ToolCall(item['call_id'], name, item['arguments'], namespace))
            elif item.get('type') == 'message':
                for part in item.get('content', []):
                    if part.get('type') == 'output_text': text.append(part['text'])
                    elif part.get('type')=='refusal':text.append(part['refusal'])
            elif item.get('type') not in ('reasoning',):
                raise ProviderError('OpenAI returned an unsupported execution item: ' + str(item.get('type')))
        return Reply(copy.deepcopy(native), '\n'.join(text), calls, response.get('usage', {}), response.get('id'))

    def close(self): self.http.close(); self.auth.close()
