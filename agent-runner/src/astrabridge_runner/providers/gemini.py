"""Google Interactions API with client-owned history and native function calls."""
import copy
from urllib.parse import urlencode

import httpx

from .http import Transport
from ..journal import json_text
from ..checkpoint_schema import output_schema
from ..types import ProviderError, Reply, ToolCall


BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'
# models.list does not currently report thinking levels or input modalities.
# These general-purpose image/tool models are documented at:
# https://ai.google.dev/gemini-api/docs/thinking
# https://ai.google.dev/gemini-api/docs/interactions-overview
MODEL_EFFORTS = {
    'gemini-4-argon': ('low', 'medium', 'high'),
    'gemini-3.8-flash': ('low', 'medium', 'high'),
    'gemini-3.7-flash': ('low', 'medium', 'high'),
    'gemini-3.6-flash': ('minimal', 'low', 'medium', 'high'),
    'gemini-3.5-flash': ('minimal', 'low', 'medium', 'high'),
    'gemini-3.5-flash-lite': ('minimal', 'low', 'medium', 'high'),
    'gemini-3.1-pro-preview': ('low', 'medium', 'high'),
    'gemini-3.1-flash-lite': ('minimal', 'low', 'medium', 'high'),
    'gemini-3-flash-preview': ('minimal', 'low', 'medium', 'high'),
    'gemini-3-pro-preview': ('low', 'high'),
    'gemini-2.5-pro': ('low', 'medium', 'high'),
    'gemini-2.5-flash': ('low', 'medium', 'high'),
    'gemini-2.5-flash-lite': ('low', 'medium', 'high'),
}


def parameters(schema):
    """Google requires even conditional required-only branches to name properties.

    Empty property schemas impose no new constraint; the enclosing schema still
    validates types and values. Do not relax an additional-properties restriction.
    """
    if isinstance(schema, list):
        return [parameters(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    result = copy.deepcopy(schema)
    # Only traverse schema locations. Literal values in const/enum/default and
    # argument names inside properties are data, even when named "required".
    for key in ('properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas'):
        if isinstance(schema.get(key), dict):
            result[key] = {name: parameters(value) for name, value in schema[key].items()}
    for key in ('items', 'contains', 'additionalProperties', 'unevaluatedProperties',
                'propertyNames', 'if', 'then', 'else', 'not', 'allOf', 'anyOf', 'oneOf', 'prefixItems'):
        if key in schema:
            result[key] = parameters(schema[key])
    missing = set(schema.get('required', [])) - set(schema.get('properties', {}))
    if missing:
        if schema.get('additionalProperties', True) is not True:
            raise ProviderError('Cannot adapt a required-only schema with restricted additional properties.')
        result.setdefault('properties', {}).update({key: {} for key in sorted(missing)})
    return result


class Gemini:
    name = 'gemini'
    streamed = False
    opaque_reasoning = True
    account = None

    def __init__(self, key, journal, model='gemini-3.8-flash', effort='high', *, client=None):
        self.key, self.journal = key, journal
        self.model, self.effort = model.removeprefix('models/'), effort
        journal.add_secret(key)
        if client is None:
            client = httpx.Client(base_url=BASE_URL + '/',
                                  timeout=httpx.Timeout(3600, connect=10, write=60, pool=30))
        self.http = Transport(journal, BASE_URL, client)

    def headers(self):
        # Keep the key out of URLs, request archives and CLI subprocesses.
        return {'x-goog-api-key': self.key}

    def request(self, method, path, **kwargs):
        try:
            return self.http.request(method, path, headers=self.headers(), **kwargs)
        except ProviderError as exc:
            raise ProviderError(self.journal.clean(str(exc)), code=exc.code, status=exc.status) from None

    @staticmethod
    def model_info(raw):
        if not isinstance(raw, dict) or not isinstance(raw.get('name'), str):
            raise ProviderError('Gemini returned a malformed model catalog entry.')
        identifier = raw['name'].removeprefix('models/')
        base = raw.get('baseModelId')
        efforts = MODEL_EFFORTS.get(identifier) or (MODEL_EFFORTS.get(base) if isinstance(base, str) else None)
        window = raw.get('inputTokenLimit')
        return {'id': identifier, 'name': raw.get('displayName', identifier),
                'context_window': window if type(window) is int and window > 1024 else None,
                'reasoning_efforts': list(efforts) if efforts else None, 'raw': copy.deepcopy(raw)}

    def models(self):
        models = []
        page = None
        seen = set()
        while True:
            query = {'pageSize': 1000}
            if page:
                query['pageToken'] = page
            response = self.request('GET', 'models?' + urlencode(query))
            rows = response.get('models')
            if not isinstance(rows, list):
                raise ProviderError('Gemini returned no model catalog.')
            models.extend(self.model_info(row) for row in rows)
            page = response.get('nextPageToken')
            if not page:
                return models
            if not isinstance(page, str) or page in seen:
                raise ProviderError('Gemini returned an invalid or repeated model page token.')
            seen.add(page)

    def check_model(self):
        models = self.models()
        info = next((item for item in models if item['id'] == self.model), None)
        if info is None:
            info = next((item for item in models if item['raw'].get('baseModelId') == self.model), None)
        if info is None:
            raise ProviderError('The requested Gemini model is not available to this API key.')
        if not info['reasoning_efforts']:
            raise ProviderError('This Gemini model has no supported image/tool and thinking configuration in this runner. '
                                'Choose a general-purpose model with listed reasoning levels, such as gemini-3.8-flash.')
        methods = info['raw'].get('supportedGenerationMethods')
        if methods is not None and (not isinstance(methods, list) or any(not isinstance(method, str) for method in methods)):
            raise ProviderError('Gemini returned malformed model capabilities.')
        if methods is not None and not any(method in methods for method in ('generateContent', 'interactions')):
            raise ProviderError('The selected Gemini model does not advertise content generation.')
        if self.effort not in info['reasoning_efforts']:
            raise ProviderError('Unsupported Gemini reasoning effort; choose ' + ', '.join(info['reasoning_efforts']) + '.')
        return info

    def definitions(self, tools):
        return [{'type': 'function', 'name': tool['name'], 'description': tool['description'],
                 'parameters': parameters(tool['input_schema'])} for tool in tools]

    def user_item(self, text):
        return {'type': 'user_input', 'content': [{'type': 'text', 'text': text}]}

    def tool_item(self, call, result):
        return {'type': 'function_result', 'call_id': call.id, 'name': call.name,
                'result': copy.deepcopy(result), 'is_error': result.get('ok') is False}

    def image_item(self, ref, caption):
        return {'type': 'user_input', 'content': [
            {'type': 'text', 'text': caption}, {'type': 'saved_image', 'image_ref': ref}]}

    def image_content(self, resources, ref):
        url = resources.content(ref)['image_url']['url']
        header, separator, data = url.partition(',')
        mime = header.removeprefix('data:').removesuffix(';base64')
        if not separator or not header.endswith(';base64') or mime not in {'image/png', 'image/jpeg', 'image/webp'}:
            raise ProviderError('Gemini screenshots must be PNG, JPEG or WebP images.')
        return {'type': 'image', 'mime_type': mime, 'data': data}

    def payload(self, instructions, items, tools, *, checkpoint=False):
        payload = {'model': self.model, 'system_instruction': instructions,
                   'input': copy.deepcopy(items), 'store': False, 'stream': False,
                   'generation_config': {'thinking_level': self.effort,
                                         'tool_choice': 'none' if checkpoint else 'auto'}}
        if checkpoint:
            payload['response_format'] = {'type': 'text', 'mime_type': 'application/json',
                                          'schema': output_schema()}
        if tools and not checkpoint:
            payload['tools'] = self.definitions(tools)
        return payload

    def complete(self, instructions, items, tools, *, checkpoint=False, on_text=None):
        response = self.request('POST', 'interactions',
                                payload=self.payload(instructions, items, tools, checkpoint=checkpoint),
                                purpose='checkpoint' if checkpoint else 'inference')
        return self.parse(response)

    def parse(self, response):
        status = response.get('status')
        if status not in {'completed', 'requires_action'}:
            raise ProviderError('Gemini interaction did not complete: ' + self.journal.clean(json_text(response)))
        steps = response.get('steps')
        if not isinstance(steps, list) or not steps:
            raise ProviderError('Gemini returned no interaction steps.')
        calls, text, identifiers = [], [], set()
        for step in steps:
            if not isinstance(step, dict):
                raise ProviderError('Gemini returned a malformed interaction step.')
            kind = step.get('type')
            if kind == 'function_call':
                if (any(not isinstance(step.get(key), str) or not step[key] for key in ('id', 'name'))
                        or not isinstance(step.get('arguments'), dict)):
                    raise ProviderError('Gemini returned a malformed function call.')
                if step['id'] in identifiers:
                    raise ProviderError('Gemini returned duplicate function call IDs.')
                identifiers.add(step['id'])
                try:
                    arguments = json_text(step['arguments'])
                except (ValueError, TypeError) as exc:
                    raise ProviderError('Gemini returned invalid function arguments.') from exc
                calls.append(ToolCall(step['id'], step['name'], arguments))
            elif kind == 'model_output':
                parts = step.get('content', [])
                if not isinstance(parts, list):
                    raise ProviderError('Gemini returned malformed model output.')
                fragments = []
                for part in parts:
                    if not isinstance(part, dict) or part.get('type') != 'text' or not isinstance(part.get('text'), str):
                        raise ProviderError('Gemini returned unsupported non-text model output.')
                    fragments.append(part['text'])
                output = ''.join(fragments)
                if output.strip():
                    text.append(output)
            elif kind == 'thought':
                if 'signature' in step and not isinstance(step['signature'], str):
                    raise ProviderError('Gemini returned a malformed thought signature.')
            else:
                # No Google Search, code execution, managed agents or server tools.
                raise ProviderError('Gemini returned an unsupported execution step: ' + str(kind))
        if status == 'requires_action' and not calls:
            raise ProviderError('Gemini requires an action but returned no function calls.')
        if not calls and not text:
            raise ProviderError('Gemini returned neither tool calls nor visible text.')
        usage = copy.deepcopy(response.get('usage', {}))
        if not isinstance(usage, dict):
            raise ProviderError('Gemini returned malformed token usage.')
        for key in ('total_input_tokens', 'total_output_tokens', 'total_thought_tokens', 'total_tokens'):
            if key in usage and (type(usage[key]) is not int or usage[key] < 0):
                raise ProviderError('Gemini returned malformed token usage.')
        if 'total_input_tokens' in usage:
            usage['input_tokens'] = usage['total_input_tokens']
        if 'total_output_tokens' in usage or 'total_thought_tokens' in usage:
            usage['output_tokens'] = usage.get('total_output_tokens', 0) + usage.get('total_thought_tokens', 0)
        if 'total_tokens' in usage and 'input_tokens' in usage:
            usage['output_tokens'] = max(usage.get('output_tokens', 0), usage['total_tokens'] - usage['input_tokens'])
        # Replay thought signatures and all native steps verbatim, including on resume.
        return Reply(copy.deepcopy(steps), '\n'.join(text), calls, usage, response.get('id'))

    def close(self):
        self.http.close()
