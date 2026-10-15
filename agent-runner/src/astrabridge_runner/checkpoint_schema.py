"""One checkpoint definition; local validation also enforces size limits."""
import copy

FIELDS = ('plan', 'facts', 'uncertainties', 'failed_attempts', 'pending_actions', 'references')
SCHEMA = {'type': 'object', 'properties': {'goal': {'type': 'string', 'minLength': 1},
          **{key: {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 40} for key in FIELDS}},
          'required': ['goal', *FIELDS], 'additionalProperties': False}
def output_schema():
    # Use the portable structural subset across providers. Local validation
    # additionally enforces minLength/maxItems and the UTF-8 byte budget.
    schema = copy.deepcopy(SCHEMA)
    schema['properties']['goal'].pop('minLength')
    for name in FIELDS:
        schema['properties'][name].pop('maxItems')
    return schema
