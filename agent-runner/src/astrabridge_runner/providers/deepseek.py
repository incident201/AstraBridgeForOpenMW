"""DeepSeek Responses transport using the common native tool/stream protocol."""
from urllib.parse import urlparse

from .responses import Responses
from ..types import ProviderError, model_info


class DeepSeek(Responses):
    name = 'deepseek'
    # DeepSeek returns reasoning_text, rather than opaque encrypted reasoning.
    opaque_reasoning = False

    def __init__(self, key, journal, base_url='https://api.deepseek.com', model='deepseek-flash', effort='max', client=None):
        parsed = urlparse(base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ProviderError('API endpoint must not contain credentials or query parameters.')
        if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ProviderError('Use HTTPS for the DeepSeek endpoint.')
        self.key = key
        journal.add_secret(key)
        super().__init__(journal, model, effort, base_url, client)

    @property
    def client(self):
        return self.http.client

    def headers(self, force=False):
        return {'Authorization': 'Bearer ' + self.key}

    def models(self):
        data = self.http.request('GET', 'models', headers=self.headers())
        return [model_info(item, self.name) for item in data.get('data', [])]

    def check_model(self):
        info = next((item for item in self.models() if item['id'] == self.model), None)
        if not info: raise ProviderError('The requested model is not advertised by DeepSeek.')
        if 'image' not in info['raw'].get('input_modalities', []): raise ProviderError('The selected DeepSeek model does not advertise images.')
        if info['reasoning_efforts'] and self.effort not in info['reasoning_efforts']: raise ProviderError('The selected model does not advertise this reasoning effort.')
        return info

    def checkpoint_format(self):
        result = super().checkpoint_format()
        # DeepSeek's Responses text.format documents schema/name, not strict.
        result.pop('strict')
        return result

    def session_state(self):
        return {'transport': 'responses'}

    def restore_session_state(self, state):
        if not isinstance(state, dict) or state.get('transport') != 'responses':
            raise ProviderError('This DeepSeek session uses the retired Chat Completions format. Start a new runner session; its logs and game saves are unchanged.')
