"""xAI Responses adapter for native AstraBridge tools and game screenshots."""
import copy
import uuid

import httpx

from .responses import Responses
from ..types import ProviderError, model_info


BASE_URL = 'https://api.x.ai/v1'
GROK_47_CONTEXT = 500000
GROK_47_EFFORTS = ['low', 'medium', 'high', 'xhigh']


class Grok(Responses):
    name = 'grok'

    def __init__(self, key, journal, model='grok-4.7', effort='xhigh', *, client=None):
        self.key = key
        journal.add_secret(key)
        self.prompt_cache_key = 'astrabridge-' + uuid.uuid4().hex
        if client is None:
            client = httpx.Client(
                base_url=BASE_URL + '/',
                timeout=httpx.Timeout(3600, connect=10, write=60, pool=30),
            )
        super().__init__(journal, model, effort, BASE_URL, client)

    def headers(self, force=False):
        return {'Authorization': 'Bearer ' + self.key}

    def models(self):
        response = self.http.request('GET', 'language-models', headers=self.headers())
        rows = response.get('models')
        if not isinstance(rows, list):
            raise ProviderError('xAI returned no language-model catalog.')
        return [self.model_info(raw) for raw in rows]

    @staticmethod
    def model_info(raw):
        if not isinstance(raw, dict):
            raise ProviderError('xAI returned a malformed language model.')
        info = model_info(raw, 'grok')
        aliases = raw.get('aliases', [])
        aliases = aliases if isinstance(aliases, list) else []
        info['aliases'] = [alias for alias in aliases if isinstance(alias, str)]
        documented = info['id'] == 'grok-4.7' or 'grok-4.7' in info['aliases']
        capabilities = raw.get('capabilities')
        capabilities = capabilities if isinstance(capabilities, dict) else {}
        if info['context_window'] is None:
            context = capabilities.get('context_window', capabilities.get('context_length'))
            if type(context) is int and context > 1024:
                info['context_window'] = context
            elif documented:
                # /language-models can omit these fields; use the documented
                # 4.7 baseline only after API discovery proves it is available.
                info['context_window'] = GROK_47_CONTEXT
        if info['reasoning_efforts'] is None:
            efforts = capabilities.get('reasoning_effort')
            if isinstance(efforts, dict):
                efforts = efforts.get('supported_levels')
            if isinstance(efforts, list) and all(isinstance(value, str) for value in efforts):
                info['reasoning_efforts'] = efforts
            elif documented:
                info['reasoning_efforts'] = list(GROK_47_EFFORTS)
        return info

    def check_model(self):
        info = next((item for item in self.models()
                     if self.model == item['id'] or self.model in item['aliases']), None)
        if info is None:
            raise ProviderError('The requested Grok model is not available to this xAI API key.')
        modalities = info['raw'].get('input_modalities')
        documented = info['id'] == 'grok-4.7' or 'grok-4.7' in info['aliases']
        if modalities is None and documented:
            modalities = ['text', 'image']
        if not isinstance(modalities, list) or 'image' not in modalities:
            raise ProviderError('The selected Grok model does not accept screenshots.')
        efforts = info['reasoning_efforts']
        if not efforts or self.effort not in efforts:
            raise ProviderError('The selected Grok model does not support this reasoning effort.')
        return info

    def payload(self, instructions, items, tools, *, checkpoint=False):
        payload = super().payload(instructions, items, tools, checkpoint=checkpoint)
        payload.pop('instructions')
        payload['input'] = [{'role': 'system', 'content': instructions}, *items]
        payload['include'] = ['reasoning.encrypted_content']
        payload['prompt_cache_key'] = self.prompt_cache_key
        return payload

    def image_content(self, resources, ref):
        image = super().image_content(resources, ref)
        image.pop('detail')
        return image

    def session_state(self):
        return {'prompt_cache_key': self.prompt_cache_key}

    def restore_session_state(self, state):
        if not state:
            return
        key = state.get('prompt_cache_key') if isinstance(state, dict) else None
        if not isinstance(key, str) or not key or len(key) > 128:
            raise ProviderError('Invalid Grok prompt cache key in the saved session.')
        self.prompt_cache_key = key

    def parse(self, response):
        reply = super().parse(response)
        # xAI can report visible completion and reasoning tokens separately.
        # Preserve every original field while adding Responses-style counters
        # for the common runner; never count reasoning a second time when
        # native output_tokens already includes it.
        usage = copy.deepcopy(reply.usage)
        if not isinstance(usage, dict):
            raise ProviderError('xAI returned malformed token usage.')
        if 'input_tokens' not in usage and 'prompt_tokens' in usage:
            usage['input_tokens'] = usage['prompt_tokens']
        if 'output_tokens' not in usage and 'completion_tokens' in usage:
            output = usage['completion_tokens'] + usage.get('reasoning_tokens', 0)
            output = max(output, usage.get('total_tokens', 0) - usage.get('input_tokens', 0))
            usage['output_tokens'] = output
        reply.usage = usage
        return reply
