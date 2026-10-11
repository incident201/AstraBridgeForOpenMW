from .responses import Responses, sse
from ..types import ProviderError, model_info


class OpenAI(Responses):
    name = 'openai'
    refresh_on_unauthorized = True

    def __init__(self, auth, journal, model, effort, *, account=None, client=None):
        self.auth = auth
        self.account = auth.resolve(account)['id']
        super().__init__(journal, model, effort, 'https://api.openai.com/v1', client)

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

    def close(self):
        try:
            super().close()
        finally:
            self.auth.close()
