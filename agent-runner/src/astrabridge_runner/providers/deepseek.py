import copy
import json
from urllib.parse import urlparse

from .http import Transport
from ..types import ProviderError, Reply, ToolCall, model_info


class DeepSeek:
    name = 'deepseek'
    streamed = False
    account = None

    def __init__(self, key, journal, base_url='https://api.deepseek.com', model='deepseek-flash', effort='max', client=None):
        parsed = urlparse(base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment: raise ProviderError('API endpoint must not contain credentials or query parameters.')
        if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'): raise ProviderError('Use HTTPS for the DeepSeek endpoint.')
        self.key, self.journal, self.model, self.effort = key, journal, model, effort
        journal.add_secret(key)
        self.http = Transport(journal, base_url, client)

    @property
    def client(self): return self.http.client

    def models(self):
        data = self.http.request('GET', 'models', headers={'Authorization': 'Bearer ' + self.key})
        return [model_info(item, self.name) for item in data.get('data', [])]

    def check_model(self):
        info = next((item for item in self.models() if item['id'] == self.model), None)
        if not info: raise ProviderError('The requested model is not advertised by DeepSeek.')
        if 'image' not in info['raw'].get('input_modalities', []): raise ProviderError('The selected DeepSeek model does not advertise images.')
        if info['reasoning_efforts'] and self.effort not in info['reasoning_efforts']: raise ProviderError('The selected model does not advertise this reasoning effort.')
        return info

    def definitions(self, tools):
        return [{'type': 'function', 'function': {'name': tool['name'], 'description': tool['description'],
                'parameters': tool['input_schema'], 'strict': False}} for tool in tools]

    def user_item(self, text): return {'role': 'user', 'content': text}
    def tool_item(self, call, result): return {'role': 'tool', 'tool_call_id': call.id, 'content': json.dumps(result, ensure_ascii=False, allow_nan=False)}
    def image_item(self, ref, caption): return {'role': 'user', 'content': [{'type': 'text', 'text': caption}, {'type': 'saved_image', 'image_ref': ref}]}
    def image_content(self, resources, ref): return resources.content(ref)

    def complete(self, instructions, items, tools, *, checkpoint=False, on_text=None):
        payload = {'model': self.model, 'messages': [{'role': 'system', 'content': instructions}, *items],
                   'stream': False, 'thinking': {'type': 'enabled'}, 'reasoning_effort': self.effort}
        if tools: payload.update(tools=self.definitions(tools), tool_choice='none' if checkpoint else 'auto')
        response = self.http.request('POST', 'chat/completions', payload=payload, headers={'Authorization': 'Bearer ' + self.key})
        choices = response.get('choices')
        if not isinstance(choices, list) or not choices or not isinstance(choices[0].get('message'), dict): raise ProviderError('DeepSeek returned no assistant message.')
        if choices[0].get('finish_reason') not in ('stop', 'tool_calls'): raise ProviderError('DeepSeek response did not complete normally.')
        message = copy.deepcopy(choices[0]['message']); message['role'] = 'assistant'
        calls = []
        for call in message.get('tool_calls') or []:
            if call.get('type') != 'function' or not isinstance(call.get('id'), str) or not isinstance(call.get('function'), dict): raise ProviderError('Malformed DeepSeek tool call.')
            function = call['function']
            if not isinstance(function.get('name'), str) or not isinstance(function.get('arguments'), str): raise ProviderError('Malformed DeepSeek tool arguments.')
            calls.append(ToolCall(call['id'], function['name'], function['arguments']))
        return Reply([message], message.get('content') or '', calls, response.get('usage', {}), response.get('id'))

    def close(self): self.http.close()
