"""A model-written memory checkpoint, without tools or a harness-owned plan."""
from jsonschema import Draft202012Validator, ValidationError

from .bridge import load_json
from .journal import json_text
from .types import ProviderError

FIELDS = ('plan', 'facts', 'uncertainties', 'failed_attempts', 'pending_actions', 'references')
SCHEMA = {'type': 'object', 'properties': {'goal': {'type': 'string', 'minLength': 1},
          **{key: {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 40} for key in FIELDS}},
          'required': ['goal', *FIELDS], 'additionalProperties': False}
INSTRUCTION = '''Create a compact historical checkpoint of this conversation. Return only a JSON object with these fields:
goal (string), plan, facts, uncertainties, failed_attempts, pending_actions, references (arrays of strings).
Record the current goal and plans already proposed by the agent. Do not invent plans, solutions, facts or references.
Separate verified observations from hypotheses and uncertainty. Preserve failed approaches and unconfirmed action outcomes.
Keep stable evidence/object/place/image references when useful; omit temporary visible_, ui_, ground_, item_, instance_ handles.
Do not copy inventory, journal text, stats or other current state that can be queried again through AstraBridge.
Preserve information needed to continue the task. Use at most 12000 UTF-8 bytes. You have no tools in this request.'''


class Compactor:
    def __init__(self, provider, journal): self.provider, self.journal = provider, journal

    def create(self, history):
        items = history.payload() + [self.provider.user_item(INSTRUCTION)]
        for attempt in range(2):
            reply = self.provider.complete(history.instructions, items, [], checkpoint=True)
            self.journal.event('checkpoint_response', attempt=attempt + 1, native=reply.native, usage=reply.usage)
            try:
                if reply.calls: raise ValueError('Checkpoint requests cannot execute tools.')
                checkpoint = load_json(reply.text)
                Draft202012Validator(SCHEMA).validate(checkpoint)
                if len(json_text(checkpoint).encode()) > 12000: raise ValueError('Checkpoint exceeds the size limit.')
                if any(ref.startswith(('visible_', 'ui_', 'ground_', 'item_', 'instance_')) for ref in checkpoint['references']):
                    raise ValueError('Checkpoint contains temporary handles.')
                return checkpoint
            except (ValueError, TypeError, ValidationError) as exc:
                # Validation errors retain the complete response in the journal.
                self.journal.event('checkpoint_invalid', attempt=attempt + 1, error=str(exc))
                if attempt == 1: raise ProviderError('Checkpoint validation failed twice. Previous context was retained.') from exc
                items.extend(reply.native)
                for call in reply.calls:
                    items.append(self.provider.tool_item(call, {'ok':False,'error':'checkpoint_tools_disabled'}))
                items.append(self.provider.user_item('The checkpoint was invalid: ' + str(exc) + '\n' + INSTRUCTION))
