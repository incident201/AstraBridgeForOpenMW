"""The rolling visual window must not rewrite the accumulated text prefix."""
import base64
import copy
from types import SimpleNamespace

import pytest

from astrabridge_runner.history import History
from astrabridge_runner.journal import Journal
from astrabridge_runner.providers.deepseek import DeepSeek
from astrabridge_runner.providers.gemini import Gemini
from astrabridge_runner.providers.grok import Grok
from astrabridge_runner.providers.openai import OpenAI
from astrabridge_runner.types import Reply, ToolCall


class Images:
    def content(self, ref):
        data = base64.b64encode(ref.encode()).decode()
        return {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + data}}


@pytest.fixture(params=[OpenAI, DeepSeek, Grok, Gemini])
def api(request, tmp_path):
    journal = Journal(tmp_path)
    cls = request.param
    if cls is OpenAI:
        auth = SimpleNamespace(resolve=lambda _: {'id': 'fixture'}, close=lambda: None)
        provider = cls(auth, journal, 'gpt-6-luna', 'low')
    else:
        provider = cls('test-key', journal, effort='low')
    try:
        yield provider, journal
    finally:
        provider.close()
        journal.close()


def cycle(history, number, image=None, historical=False):
    provider = history.provider
    call = ToolCall(f'call_{number}', 'astra_observe', '{}')
    if provider.name == 'gemini':
        native = [{'type': 'thought', 'signature': f'signed-{number}'},
                  {'type': 'function_call', 'id': call.id, 'name': call.name, 'arguments': {}}]
    else:
        native = [{'type': 'reasoning', 'encrypted_content': f'opaque-{number}', 'summary': []},
                  {'type': 'function_call', 'call_id': call.id, 'name': call.name, 'arguments': '{}'}]
        if provider.name == 'deepseek':
            native[0] = {'type': 'reasoning', 'content': [{'type': 'reasoning_text', 'text': f'Reasoning {number}'}]}
    history.assistant(Reply(native, ''), [{'call': call.dump()}])
    result = {'ok': True, 'result': {'observation': number, 'diagnostics': 'Keep all of this.',
                                  'scene': {'objects': [{'ref': f'visible_{number}'}]}}}
    history.tool(call, result, image=image, historical=historical)
    return native, provider.tool_item(call, result)


def has_image(item):
    return any(part.get('type') in ('image', 'input_image') for part in item.get('content', [])
               if isinstance(part, dict))


def split(payload):
    first = next((i for i, item in enumerate(payload) if has_image(item)), len(payload))
    assert all(has_image(item) for item in payload[first:])
    return payload[:first], payload[first:]


@pytest.mark.parametrize('limit', [1, 2])
def test_text_prefix_is_append_only_across_image_eviction(api, limit):
    provider, journal = api
    history = History(provider, 'Rules', journal, Images(), image_limit=limit)
    history.user('Reach the door.')
    previous = []
    native_history = []
    for number in range(1, 5):
        native, result = cycle(history, number, f'image_{number}')
        native_history.extend(native + [result])
        before = copy.deepcopy(history.snapshot())
        payload = history.payload()
        text, attachments = split(payload)
        assert history.snapshot() == before  # Includes original image markers.
        assert text[:len(previous)] == previous
        assert len(attachments) == min(number, limit)
        assert all(item in text for item in native_history)
        expected = list(range(max(1, number-limit+1), number+1))
        for item, selected in zip(attachments, expected):
            assert f'image_{selected}' in str(item) and f'call_{selected}' in str(item)
            assert 'not a new observation' in str(item)
        for old in range(1, number+1):
            assert f'Image image_{old}, returned with tool call call_{old}.' in str(text)
        assert 'saved_image' not in str(payload)
        previous = text


def test_reselecting_old_image_retains_historical_label_and_deduplicates(api):
    provider, journal = api
    history = History(provider, 'Rules', journal, Images(), image_limit=2)
    cycle(history, 1, 'image_1')
    cycle(history, 2, 'image_2')
    before, _ = split(history.payload())
    cycle(history, 3, 'image_1', historical=True)
    text, tail = split(history.payload())
    assert text[:len(before)] == before
    assert len(tail) == 2
    assert 'image_2' in str(tail[0]) and 'call_2' in str(tail[0])
    assert 'Historical image image_1' in str(tail[1]) and 'call_3' in str(tail[1])
    stable = history.payload()
    cycle(history, 4)  # A text-only tool must keep exactly the same images.
    _, new_tail = split(history.payload())
    assert new_tail == tail
    assert stable != history.payload()  # New tool result is still present.


def test_resume_existing_context_and_compaction_keep_image_sources(api):
    provider, journal = api
    history = History(provider, 'Rules', journal, Images())
    history.user('Reach the door.')
    for number in range(1, 4):
        cycle(history, number, f'image_{number}')
    state = copy.deepcopy(history.snapshot())
    resumed = History(provider, 'Ignored on resume', journal, Images(), state=state)
    assert resumed.payload() == history.payload()
    # Same persisted format as before this layout change: no tail is stored.
    assert all('Screenshot attachment' not in str(cycle) for cycle in state['cycles'])
    resumed.checkpoint = {'goal': 'Reach the door.', 'facts': ['A rock blocks the path.']}
    resumed.cycles = copy.deepcopy(resumed.cycles[-1:])
    text, tail = split(resumed.payload())
    assert len(tail) == 1 and 'image_3' in str(tail[0]) and 'call_3' in str(tail[0])
    assert 'Historical model-generated checkpoint' in str(text)
    assert 'image_1' not in str(resumed.payload())
    prior = text
    cycle(resumed, 4, 'image_4')
    assert split(resumed.payload())[0][:len(prior)] == prior


def test_text_only_history_does_not_gain_attachment_messages(api):
    provider, journal = api
    history = History(provider, 'Rules', journal, Images())
    history.user('Read the journal.')
    cycle(history, 1)
    text, tail = split(history.payload())
    assert not tail and 'Screenshot attachment' not in str(text)
    assert text[1:] == history.messages
