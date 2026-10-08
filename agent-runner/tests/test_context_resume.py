import json
from types import SimpleNamespace

import pytest

from astrabridge_runner.compaction import Compactor
from astrabridge_runner.journal import Journal
from astrabridge_runner.providers.deepseek import DeepSeek
from astrabridge_runner.runner import Runner
from astrabridge_runner.types import ProviderError, Reply, ToolCall


CHECKPOINT = {'goal': 'Find the captain', 'plan': ['Check the unvisited passage'], 'facts': ['The previous door is locked'],
              'uncertainties': ['The passage destination is not yet confirmed'], 'failed_attempts': ['Direct approach stopped at a wall'],
              'pending_actions': [], 'references': ['image_000001']}


class Provider(DeepSeek):
    def __init__(self, journal, replies=None):
        super().__init__('secret-test-key', journal, model='deepseek-flash', effort='max')
        self.replies = list(replies or []); self.requests = []; self.checkpoints = []
    def check_model(self): return {'id': self.model, 'name': 'Fixture', 'context_window': 200000, 'reasoning_efforts': ['max'], 'raw': {}}
    def complete(self, instructions, items, tools, **options):
        self.requests.append({'instructions': instructions, 'items': items, 'tools': tools, **options})
        if options.get('checkpoint'):
            value = self.checkpoints.pop(0) if self.checkpoints else json.dumps(CHECKPOINT)
            return Reply([{'role': 'assistant', 'content': value, 'reasoning_content': 'Summary reasoning'}], value)
        return self.replies.pop(0)


def reply(n, *, large=False, usage=25000, name='astra_observe'):
    call = ToolCall(f'call_{n}', name, '{}')
    message = {'role': 'assistant', 'content': ('old_observation ' * 10000) if large else f'Step {n}',
               'reasoning_content': f'Full reasoning {n}',
               'tool_calls': [{'id': call.id, 'type': 'function', 'function': {'name': name, 'arguments': '{}'}}]}
    return Reply([message], message['content'], [call], {'prompt_tokens': usage, 'completion_tokens': 200})


def test_checkpoint_compaction_keeps_goal_pairs_and_full_journal(fixture):
    f = fixture; api = Provider(f['journal'], [reply(0, large=True), *[reply(n) for n in range(1, 12)],
        reply(12, usage=160000), Reply([{'role': 'assistant', 'content': 'Done', 'reasoning_content': 'Final reasoning'}], 'Done', usage={'prompt_tokens': 30000, 'completion_tokens': 50})])
    runner = Runner(f['skill'], f['journal'], api, output=lambda _: None)
    try:
        runner.prepare(); runner.turn('Find the captain')
        checkpoints = [event for event in f['journal'].records() if event['kind'] == 'context_compacted']
        assert len(checkpoints) == 1
        active = json.loads((f['journal'].root/'active-state.json').read_text())
        assert active['checkpoint'] == CHECKPOINT and active['task'] == 'Find the captain'
        assert 'old_observation' not in json.dumps(active)
        assert 'old_observation' in (f['journal'].root/'events.jsonl').read_text()
        for cycle in active['cycles']:
            call_ids = [call['id'] for item in cycle['items'] for call in item.get('tool_calls', [])]
            outputs = [item['tool_call_id'] for item in cycle['items'] if item.get('role') == 'tool']
            assert call_ids == outputs
        summary = [request for request in api.requests if request.get('checkpoint')]
        assert len(summary) == 1 and not summary[0]['tools']
        assert 'Do not copy inventory' in json.dumps(summary[0])
    finally: runner.close()


def test_bad_checkpoints_leave_active_context_untouched(fixture):
    f = fixture; api = Provider(f['journal']); api.checkpoints = ['not JSON', json.dumps({**CHECKPOINT, 'unexpected': True})]
    runner = Runner(f['skill'], f['journal'], api, output=lambda _: None)
    try:
        runner.prepare(); runner.history.user('Find the captain')
        before = (f['journal'].root/'active-state.json').read_bytes()
        with pytest.raises(ProviderError, match='twice'): Compactor(api, f['journal']).create(runner.history)
        assert (f['journal'].root/'active-state.json').read_bytes() == before
        assert len([event for event in f['journal'].records() if event['kind'] == 'checkpoint_invalid']) == 2
    finally: runner.close()


@pytest.mark.parametrize('stage', ['executed', 'unknown', 'not_started'])
def test_resume_resolves_pending_calls_without_reexecuting_mutations(fixture, stage):
    f = fixture; api = Provider(f['journal']); runner = Runner(f['skill'], f['journal'], api, output=lambda _: None)
    runner.prepare(); runner.history.user('Find the captain')
    model_reply = reply(1, name='astra_act'); execution = 'interrupted-execution'
    pending = [{'call': model_reply.calls[0].dump(), 'execution_id': execution}]
    runner.history.assistant(model_reply, pending)
    if stage == 'executed':
        runner.bridge.call('astra_act', '{}', model_reply.calls[0].id, execution)
    elif stage == 'unknown':
        f['journal'].event('tool_start', name='astra_act', call_id=model_reply.calls[0].id, execution_id=execution, request_id='receipt-id', arguments={})
    folder = f['journal'].root; runner.close()
    journal = Journal(folder.parent, resume=folder); second_api = Provider(journal)
    second = Runner(f['skill'], journal, second_api, output=lambda _: None)
    try:
        second.prepare(resume=True)
        calls = [json.loads(line) for line in (f['root']/'calls.jsonl').read_text().splitlines()]
        assert sum(row['args'][:2] == ['game', 'act'] for row in calls) == (1 if stage == 'executed' else 0)
        payload = second.history.payload()
        results = [json.loads(item['content']) for item in payload if item.get('role') == 'tool']
        assert len(results) == 1
        if stage == 'executed': assert results[0]['ok'] and 'motion' in results[0]['result']['action']
        elif stage == 'unknown': assert results[0]['result_unknown'] and results[0]['request_id'] == 'receipt-id'
        else: assert results[0]['error'] == 'tool_not_executed' and not results[0]['result_unknown']
        assert 'historical' in json.dumps(payload)
        assert not any(cycle['pending'] for cycle in second.history.cycles)
    finally: second.close()


def test_resume_rejects_changed_game_profile_before_connecting(fixture):
    f = fixture; runner = Runner(f['skill'], f['journal'], Provider(f['journal']), output=lambda _: None)
    runner.prepare(); runner.history.user('Find the captain'); folder = f['journal'].root; runner.close()
    manifest = json.loads((folder/'manifest.json').read_text()); manifest['installation']['profile'] = 'other-profile'
    (folder/'manifest.json').write_text(json.dumps(manifest))
    journal = Journal(folder.parent, resume=folder); second = Runner(f['skill'], journal, Provider(journal), output=lambda _: None)
    before = len((f['root']/'calls.jsonl').read_text().splitlines())
    try:
        with pytest.raises(Exception, match='profile differs'): second.prepare(resume=True)
        calls = [json.loads(line) for line in (f['root']/'calls.jsonl').read_text().splitlines()][before:]
        assert not any(row['args'][:2] == ['agent', 'connect'] for row in calls)
    finally: second.close()


def test_resume_releases_only_its_interrupted_connection(fixture):
    f = fixture; first = Runner(f['skill'], f['journal'], Provider(f['journal']), output=lambda _: None)
    first.prepare(); first.history.user('Find the captain'); folder = f['journal'].root
    # Simulate process death: retain the private credential file and server
    # lease, and close the journal without running the ordinary disconnect.
    first.api.close(); first.journal.close()
    journal = Journal(folder.parent, resume=folder); second = Runner(f['skill'], journal, Provider(journal), output=lambda _: None)
    try:
        second.prepare(resume=True)
        assert any(row['kind'] == 'interrupted_connection_released' for row in journal.records())
        assert second.bridge.owned
    finally:
        second.close()
        if first.bridge.private:first.bridge.private.cleanup()
