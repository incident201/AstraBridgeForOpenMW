"""MiMo Chat Completions wire adapter over the runner's canonical history."""

import copy
import json

import httpx

from .responses import Responses, sse
from .http import RETRY_STATUSES
from ..types import ProviderError, model_info


EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')
VISION_MODELS = ('mimo-v2.6-pro', 'mimo-v2.6-flash', 'mimo-v2.6-pro-ultraspeed')


class MiMo(Responses):
    name = 'mimo'
    opaque_reasoning = False

    def __init__(self, key, journal, model='mimo-v2.6-pro', effort='high', client=None):
        self.key = key
        journal.add_secret(key)
        super().__init__(journal, model, effort, 'https://api.xiaomimimo.com/v1', client)

    def headers(self, force=False):
        return {'api-key': self.key}

    def models(self):
        data = self.http.request('GET', 'models', headers=self.headers())
        result = []
        for raw in data.get('data', []):
            info = model_info(raw, self.name)
            if info['id'] in VISION_MODELS:
                # The catalog documents IDs only; use the published V2.6 limits.
                info['context_window'] = info['context_window'] or 1_000_000
                info['reasoning_efforts'] = list(EFFORTS)
            result.append(info)
        return result

    def check_model(self):
        info = next((item for item in self.models() if item['id'] == self.model), None)
        if not info:
            raise ProviderError('The requested model is not advertised by MiMo.')
        modalities = info['raw'].get('input_modalities')
        if (modalities is not None and 'image' not in modalities) or (
            modalities is None and self.model not in VISION_MODELS
        ):
            raise ProviderError('The selected MiMo model has no known image support.')
        if self.effort not in (info['reasoning_efforts'] or EFFORTS):
            raise ProviderError('Unsupported MiMo reasoning effort. Use none to disable thinking, or high to enable it.')
        return info

    def payload(self, instructions, items, tools, *, checkpoint=False):
        payload = {
            'model': self.model,
            'messages': [{'role': 'system', 'content': instructions}, *chat_messages(items)],
            'stream': True,
            'stream_options': {'include_usage': True},
            'thinking': {'type': 'disabled' if self.effort == 'none' else 'enabled'},
        }
        if checkpoint:
            payload['response_format'] = self.checkpoint_format()
        elif tools:
            payload['tools'] = [{'type': 'function', 'function': {
                'name': tool['name'], 'description': tool['description'],
                'parameters': tool['input_schema'], 'strict': False,
            }} for tool in tools]
            payload['tool_choice'] = 'auto'
        return payload

    def complete(self, instructions, items, tools, *, checkpoint=False, on_text=None):
        payload = self.payload(instructions, items, tools, checkpoint=checkpoint)
        for attempt in range(3):
            index, start = self.http.begin('POST', 'chat/completions', payload, attempt,
                                         purpose='checkpoint' if checkpoint else 'inference')
            status, headers, events = None, {}, []
            output = ChatOutput()
            try:
                with self.http.client.stream('POST', 'chat/completions', json=payload,
                                             headers=self.headers()) as response:
                    status, headers = response.status_code, response.headers
                    if not response.is_success:
                        response.read()
                        try:
                            body = response.json()
                        except ValueError:
                            body = {'detail': response.text}
                        self.http.finish(index, start, status, headers, body)
                        if status in RETRY_STATUSES and attempt < 2 and self.http.wait_to_retry(attempt, headers):
                            continue
                        raise ProviderError(f'MiMo API returned HTTP {status}: ' +
                                            self.journal.clean(json.dumps(body)), status=status)
                    for event in sse(response.iter_lines()):
                        events.append(event)
                        self.journal.event('stream_event', index=index, event=event)
                        text = output.accept(event)
                        if text and on_text and not checkpoint:
                            on_text(text)
                completed = output.finish()
            except BaseException as exc:
                if status is None and isinstance(exc, httpx.TransportError) and attempt < 2:
                    self.http.finish(index, start, status, headers, {'transport_error': str(exc)})
                    self.http.wait_to_retry(attempt, {})
                    continue
                if status is None or status < 400:
                    self.http.finish(index, start, status, headers,
                                     {'events': events, 'usage': output.usage, 'error': str(exc)})
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                raise ProviderError(self.journal.clean(str(exc)), status=status) from exc
            self.http.finish(index, start, status, headers, {'events': events, **completed})
            return self.parse(completed)
        raise ProviderError('MiMo API retries exhausted.')

    def checkpoint_format(self):
        # MiMo supports JSON mode, not schema-constrained text output. The
        # shared checkpoint prompt supplies the fields; Compactor validates it.
        return {'type': 'json_object'}

    def image_content(self, resources, ref):
        content = super().image_content(resources, ref)
        content.pop('detail')
        return content


def chat_messages(items):
    """Group one assistant turn's reasoning, prose and calls in one message.

    Keep canonical saved history unchanged, including older Responses sessions.
    Only the outgoing MiMo wire representation changes.
    """
    messages = []
    for item in items:
        kind = item.get('type')
        if kind in ('reasoning', 'function_call', 'message'):
            if not messages or messages[-1]['role'] != 'assistant':
                messages.append({'role': 'assistant', 'content': '', 'reasoning_content': ''})
            message = messages[-1]
            if kind == 'reasoning':
                for part in item.get('content', []):
                    if part.get('type') != 'reasoning_text':
                        raise ProviderError('Unsupported MiMo reasoning content.')
                    message['reasoning_content'] += part['text']
            elif kind == 'message':
                for part in item.get('content', []):
                    if part.get('type') == 'output_text':
                        message['content'] += part['text']
                    elif part.get('type') == 'refusal':
                        message['content'] += part['refusal']
                    else:
                        raise ProviderError('Unsupported MiMo assistant content.')
            else:
                message.setdefault('tool_calls', []).append({
                    'id': item['call_id'], 'type': 'function',
                    'function': {'name': item['name'], 'arguments': item['arguments']},
                })
        elif kind == 'function_call_output':
            messages.append({'role': 'tool', 'tool_call_id': item['call_id'], 'content': item['output']})
        elif item.get('role') in ('user', 'system', 'developer', 'assistant'):
            content = item['content']
            if isinstance(content, list):
                parts = []
                for part in content:
                    if part['type'] in ('input_text', 'output_text'):
                        parts.append({'type': 'text', 'text': part['text']})
                    elif part['type'] == 'input_image':
                        parts.append({'type': 'image_url', 'image_url': {'url': part['image_url']}})
                    else:
                        raise ProviderError('Unsupported MiMo input content.')
                content = parts
            messages.append({'role': item['role'], 'content': content})
        else:
            raise ProviderError('Unsupported MiMo history item.')
    return messages


class ChatOutput:
    """Accumulate native chunks; incomplete or conflicting calls never execute."""

    def __init__(self):
        self.identifier = None
        self.text = ''
        self.reasoning = ''
        self.calls = {}
        self.usage = {}
        self.finished = None

    def accept(self, event):
        if event.get('error'):
            raise ProviderError('MiMo stream failed: ' + json.dumps(event['error']))
        if event.get('id'):
            if self.identifier and self.identifier != event['id']:
                raise ProviderError('MiMo stream changed response ID.')
            self.identifier = event['id']
        if event.get('usage'):
            self.usage = copy.deepcopy(event['usage'])
        choices = event.get('choices', [])
        if not choices:
            return ''  # Usage-only final chunk.
        if len(choices) != 1 or choices[0].get('index') != 0 or self.finished:
            raise ProviderError('Unexpected MiMo completion choices.')
        choice = choices[0]
        delta = choice.get('delta', {})
        text = delta.get('content') or ''
        self.text += text
        self.text += delta.get('refusal') or ''
        self.reasoning += delta.get('reasoning_content') or ''
        for part in delta.get('tool_calls') or []:
            position = part.get('index')
            if type(position) is not int or position < 0 or part.get('type', 'function') != 'function':
                raise ProviderError('Malformed MiMo tool-call chunk.')
            call = self.calls.setdefault(position, {'call_id': '', 'name': '', 'arguments': ''})
            if part.get('id'):
                if call['call_id'] and call['call_id'] != part['id']:
                    raise ProviderError('MiMo stream changed tool-call ID.')
                call['call_id'] = part['id']
            function = part.get('function') or {}
            call['name'] += function.get('name') or ''
            call['arguments'] += function.get('arguments') or ''
        if choice.get('finish_reason'):
            self.finished = choice['finish_reason']
        return text

    def finish(self):
        if self.finished not in ('stop', 'tool_calls'):
            raise ProviderError('MiMo stream did not finish successfully. No tools were executed.')
        if bool(self.calls) != (self.finished == 'tool_calls'):
            raise ProviderError('MiMo finish reason disagrees with its tool calls.')
        if sorted(self.calls) != list(range(len(self.calls))):
            raise ProviderError('MiMo stream contains unfinished tool calls.')
        output = []
        if self.reasoning:
            output.append({'type': 'reasoning', 'summary': [], 'content': [
                {'type': 'reasoning_text', 'text': self.reasoning}]})
        if self.text:
            output.append({'type': 'message', 'role': 'assistant', 'content': [
                {'type': 'output_text', 'text': self.text}]})
        for position in sorted(self.calls):
            call = self.calls[position]
            if not call['call_id'] or not call['name']:
                raise ProviderError('MiMo stream returned an incomplete function call.')
            output.append({'type': 'function_call', 'status': 'completed', **call})
        return {'id': self.identifier, 'status': 'completed', 'output': output, 'usage': self.usage}
