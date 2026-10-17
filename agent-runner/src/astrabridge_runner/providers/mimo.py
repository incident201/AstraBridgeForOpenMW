"""Xiaomi MiMo through its native Responses-compatible endpoint."""

from .responses import Responses
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
        payload = super().payload(instructions, items, tools, checkpoint=checkpoint)
        # These OpenAI fields are not part of MiMo's documented contract.
        # The runner owns history and independently enforces sequential calls.
        payload.pop('store')
        payload.pop('parallel_tool_calls')
        return payload

    def checkpoint_format(self):
        # MiMo supports JSON mode, not schema-constrained text output. The
        # shared checkpoint prompt supplies the fields; Compactor validates it.
        return {'type': 'json_object'}

    def image_content(self, resources, ref):
        content = super().image_content(resources, ref)
        content.pop('detail')
        return content
