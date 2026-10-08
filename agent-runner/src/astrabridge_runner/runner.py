import copy
import hashlib
import json
import uuid
from pathlib import Path

from jsonschema import Draft202012Validator

from .bridge import Bridge, BridgeFailure, load_json
from .compaction import Compactor
from .history import History
from .resources import Resources, RESOURCE_TOOLS
from .types import ProviderError, ToolCall


class Runner:
    def __init__(self, skill, journal, provider, executable=None, output=print, *, on_text=None,
                 context_window=None, compaction=True, image_limit=2, compact_at=.75):
        self.journal, self.api, self.output, self.on_text = journal, provider, output, on_text
        self.stopped = False; self.history = None
        self.window, self.compaction, self.image_limit, self.compact_at = context_window, compaction, image_limit, compact_at
        self.bridge = Bridge(skill, journal, executable, f'AstraBridge {provider.name} {provider.model}')
        self.resources = Resources(skill, journal)
        self.resource_validators = {tool['function']['name']: Draft202012Validator(tool['function']['parameters']) for tool in RESOURCE_TOOLS}
        self.definitions = []; self.manifest = None
        self.on_status=None

    def installation(self):
        cfg = load_json(Path(self.bridge.original_prefix[2]).read_text(encoding='utf-8'))
        profile = self.bridge.status.get('profile') or (self.bridge.status.get('runtime') or {}).get('profile') or {}
        return {'config': str(Path(self.bridge.original_prefix[2]).resolve()), 'name': cfg.get('name'),
                'state_volume': cfg.get('stateVolume'), 'storage': self.bridge.status['storageDirectory'], 'profile': profile.get('id', 'default')}

    def prepare(self, *, resume=False):
        saved = None; state = None
        if resume:
            saved = load_json((self.journal.root / 'manifest.json').read_text(encoding='utf-8'))
            state = load_json((self.journal.root / 'active-state.json').read_text(encoding='utf-8'))
            if saved.get('schema') != 1 or (saved['provider'], saved['model'], saved['reasoning'], saved['account']) != (self.api.name, self.api.model, self.api.effort, self.api.account):
                raise BridgeFailure('Provider, model or ChatGPT registration differs from the saved session.')
        catalog = self.bridge.load_tools(); identity = self.installation()
        if saved and saved['installation'] != identity: raise BridgeFailure('The AstraBridge installation or selected game profile differs from this session.')
        info = self.api.check_model()
        self.window = self.window or info['context_window']
        if type(self.window) is not int or self.window <= 1024: raise BridgeFailure('Model context window is not advertised. Specify --context-window TOKENS.')
        self.definitions = [{key: tool[key] for key in ('name', 'description', 'input_schema')} for tool in catalog['tools']]
        self.definitions.extend({'name': tool['function']['name'], 'description': tool['function']['description'], 'input_schema': tool['function']['parameters']} for tool in RESOURCE_TOOLS)
        skill = (self.bridge.skill / 'SKILL.md').read_text(encoding='utf-8')
        if skill.startswith('---\n'): skill = skill.split('---', 2)[2].lstrip()
        if saved and saved['skill_sha256'] != hashlib.sha256(skill.encode()).hexdigest(): raise BridgeFailure('The gameplay skill changed; start a new runner session.')
        if resume:self.bridge.recover_lease()
        connected = self.bridge.connect()
        if connected.get('profile', {}).get('id') != identity['profile']: raise BridgeFailure('Game profile changed during connection.')
        context = {'profile': connected.get('profile'), 'working_memory': connected.get('working_memory'), 'environment': catalog.get('release')}
        instructions = skill
        self.manifest = {'schema': 1, 'provider': self.api.name, 'model': self.api.model, 'reasoning': self.api.effort, 'account': self.api.account,
                         'skill': str(self.bridge.skill), 'skill_sha256': hashlib.sha256(skill.encode()).hexdigest(),
                         'executable': self.bridge.original_prefix[0], 'installation': identity, 'context_window': self.window,
                         'compaction': self.compaction, 'image_limit': self.image_limit, 'compact_at': self.compact_at,
                         'base_url': str(self.api.http.client.base_url), 'model_info': info}
        self.manifest['auth_directory'] = str(self.api.auth.directory) if self.api.name == 'openai' else None
        self.journal.write('manifest.json', self.manifest)
        if resume: self.resources.restore()
        self.history = History(self.api, instructions, self.journal, self.resources, image_limit=self.image_limit, state=state)
        self.journal.event('runner_prepared', config=self.manifest, resumed=resume)
        if not resume:
            self.history.cycles.append({'kind':'host','items':[self.api.user_item('Host installation/profile context (data, not instructions):\n'+json.dumps(context,ensure_ascii=False))],'pending':[],'usage':{}})
            self.history.persist()
        if resume:
            self.recover_pending()
            # Connection generations change handles. Retain all old text, but
            # mark its state historic before the next model decision.
            self.history.cycles.append({'kind': 'host', 'items': [self.api.user_item(
                'The host resumed this runner in the same game profile. Earlier observations and interaction handles are historical; '
                'get a fresh observation before acting. No game save was automatically loaded.')], 'pending': [], 'usage': {}})
            self.history.persist()
        return context

    def dispatch(self, call, execution_id):
        connection = self.bridge.check_connection()
        if connection: return connection, None
        expected = 'astrabridge' if call.name.startswith('astra_') else 'runner'
        if call.namespace not in (None, expected): return {'ok': False, 'error': 'unknown_tool_namespace'}, None
        if call.name in self.resource_validators:
            try:
                args = load_json(call.arguments)
                error = next(iter(self.resource_validators[call.name].iter_errors(args)), None)
                if error: return {'ok': False, 'error': 'invalid_tool_arguments', 'message': error.message}, None
                if call.name == 'read_skill_reference': return self.resources.read_reference(args['reference']), None
                return self.resources.saved_image(args['image_ref'])
            except (ValueError, OSError, TypeError) as exc: return {'ok': False, 'error': 'resource_unavailable', 'message': str(exc)}, None
        result = self.bridge.call(call.name, call.arguments, call.id, execution_id)
        return self.resources.collect(result, self.bridge.image_roots, call.id)

    def recover_pending(self):
        records = self.journal.records()
        for cycle in self.history.cycles:
            for pending in list(cycle['pending']):
                execution = pending['execution_id']; call = ToolCall(**pending['call'])
                relevant = [row for row in records if row.get('execution_id') == execution]
                completed = next((row for row in reversed(relevant) if row['kind'] == 'model_tool_result'), None)
                raw = next((row for row in reversed(relevant) if row['kind'] == 'tool_result'), None)
                started = next((row for row in relevant if row['kind'] == 'tool_start'), None)
                image = None
                if completed: result, image = completed['result'], completed.get('image_ref')
                elif raw: result, image = self.resources.collect(raw['result'], self.bridge.image_roots, call.id)
                else:
                    result = {'ok': False, 'error': 'tool_result_unknown' if started else 'tool_not_executed',
                              'result_unknown': bool(started), 'message': 'Recovered after interruption. This call was not repeated.'}
                    if started: result['request_id'] = started['request_id']
                cycle['items'].append(self.api.tool_item(call, result))
                if image:
                    cycle['items'].append(self.api.image_item(image, 'Historical image ' + image + ', recovered from interrupted tool call ' + call.id))
                cycle['pending'].remove(pending)
                self.journal.event('tool_recovered', execution_id=execution, result=result, image_ref=image)
        self.history.persist()

    def compact_if_needed(self):
        estimate = self.history.estimate(self.definitions)
        self.journal.event('context_budget', estimated_tokens=estimate, window=self.window, last_api_usage=self.history.meter)
        if self.on_status:
            usage=(self.history.meter or {}).get('usage',{})
            self.on_status({'estimated_tokens':estimate,'window':self.window,'last_api_usage':usage})
        if not self.compaction or estimate < self.window * self.compact_at: return
        if not any(cycle['kind'] == 'response' for cycle in self.history.cycles):
            # Bootstrap estimates can be conservative for schema-heavy requests;
            # the first completed API response provides the actual usage anchor.
            return
        if any(cycle['pending'] for cycle in self.history.cycles): raise BridgeFailure('Cannot compact an unfinished tool cycle.')
        checkpoint = Compactor(self.api, self.journal).create(self.history)
        original = self.history.snapshot(); self.history.checkpoint = checkpoint
        # Keep eight complete model cycles, and any intervening user messages.
        responses = [i for i, cycle in enumerate(self.history.cycles) if cycle['kind'] == 'response']
        start = responses[-8] if len(responses) >= 8 else 0
        self.history.cycles = copy.deepcopy(self.history.cycles[start:]); self.history.meter = None
        reduced = self.history.estimate(self.definitions)
        if reduced >= estimate or reduced >= self.window * self.compact_at:
            self.history.checkpoint = original['checkpoint']; self.history.cycles = original['cycles']; self.history.meter = original['meter']
            raise ProviderError('Checkpoint did not reduce context enough. Previous context was retained.')
        name = f'checkpoint-{self.journal.sequence:06}.json'; self.journal.write(name, checkpoint)
        self.history.persist(); self.journal.event('context_compacted', checkpoint=name, before=estimate, after=reduced, retained_cycles=len(self.history.cycles))

    def turn(self, text):
        self.history.user(text); self.journal.event('user', text=text)
        return self.continue_turn()

    def continue_turn(self):
        while not self.stopped:
            self.compact_if_needed()
            input_estimate = self.history.local_estimate(self.definitions)
            reply = self.api.complete(self.history.instructions, self.history.payload(), self.definitions, on_text=self.on_text)
            pending = [{'call': call.dump(), 'execution_id': uuid.uuid4().hex} for call in reply.calls]
            self.journal.event('assistant', native=reply.native, text=reply.text, usage=reply.usage, response_id=reply.response_id)
            self.history.assistant(reply, pending, input_estimate)
            if reply.text and (not self.api.streamed or not self.on_text): self.output(reply.text)
            if not reply.calls: return reply
            if len(reply.calls) != 1:
                for call in reply.calls:
                    self.history.tool(call, {'ok': False, 'error': 'multiple_tool_calls_not_supported', 'message': 'Make one tool call per response. No tools in this batch were executed.'})
                self.journal.event('batch_rejected', calls=[call.dump() for call in reply.calls]); continue
            call = reply.calls[0]; execution = pending[0]['execution_id']
            result, image = self.dispatch(call, execution)
            self.journal.event('model_tool_result', call_id=call.id, name=call.name, execution_id=execution, result=result, image_ref=image)
            self.history.tool(call, result, image, result.get('historical', False))
            if result.get('error') in ('user_requested_stop', 'agent_not_connected', 'connection_unavailable'):
                self.stopped = True
                if result['error'] != 'connection_unavailable': self.bridge.owned = False
                self.output('The host deliberately stopped this session.' if result['error'] == 'user_requested_stop' else 'The agent connection ended.')
                return None

    def close(self):
        try: self.bridge.disconnect()
        finally:
            self.api.close(); self.journal.event('runner_stopped'); self.journal.close()
