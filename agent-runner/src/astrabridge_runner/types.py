from dataclasses import dataclass, field


class ProviderError(RuntimeError):
    def __init__(self, message, *, code=None, status=None):
        super().__init__(message)
        self.code, self.status = code, status


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str
    namespace: str | None = None

    def dump(self): return vars(self).copy()


@dataclass
class Reply:
    native: list[dict]
    text: str
    calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    response_id: str | None = None


def model_info(raw, provider):
    identifier = raw.get('slug') if provider == 'openai' else raw.get('id')
    if not isinstance(identifier, str): raise ProviderError('The provider returned a model without an identifier.')
    window = raw.get('context_window', raw.get('context_length'))
    if type(window) is not int or window <= 1024: window = None
    efforts = raw.get('supported_reasoning_efforts', raw.get('supported_reasoning_levels', (raw.get('effort') or {}).get('supported_levels')))
    efforts = [v.get('reasoning_effort', v.get('effort')) if isinstance(v, dict) else v for v in efforts] if isinstance(efforts, list) else None
    return {'id': identifier, 'name': raw.get('display_name', raw.get('name', identifier)),
            'context_window': window, 'reasoning_efforts': efforts, 'raw': raw}
