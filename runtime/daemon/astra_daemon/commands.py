"""One command catalog shared by the Python Game API and the packaged TS CLI."""
import argparse
import json
import copy
import re
from pathlib import Path

from astra_bridge.cli import build_parser
from astra_bridge.argument_specs import (ACT_SCHEMA, CHAIN_SCHEMA, CHECKPOINT_SCHEMA,
    SEQUENCE_OPS, SEQUENCE_PROPERTIES, SELECTOR_SCHEMA, EXPECT_SCHEMA, ACTION_DEFAULTS, object_schema)
from astra_bridge.argument_specs import (KNOWLEDGE_ACTION_FIELDS, MAP_ARGUMENT_FIELDS,
    CLI_REQUEST_TIMEOUT, LONG_ACTION_TIMEOUT, ACTION_TIMEOUT_MULTIPLIER)
from astra_bridge.selectors import REF_OPS, source_for

EXCLUDED={'start','serve','shutdown','restart','version'}


def catalog():
    parser=build_parser()
    commands=next(a for a in parser._actions if isinstance(a,argparse._SubParsersAction)).choices
    result={}
    for name,command in commands.items():
        if name in EXCLUDED:continue
        fields=[]
        for action in command._actions:
            if isinstance(action,argparse._HelpAction):continue
            kind=('boolean' if isinstance(action,(argparse._StoreTrueAction,argparse.BooleanOptionalAction))
                  else 'json' if action.type is json.loads else 'number' if action.type in (int,float)
                  else 'string')
            field={'name':action.dest,'options':action.option_strings,'type':kind,'integer':action.type is int,'required':action.required,
                   'optional':action.nargs=='?','array':isinstance(action,argparse._AppendAction)}
            if action.default is not None and action.default!=argparse.SUPPRESS:field['default']=action.default
            if action.choices is not None:field['choices']=list(action.choices)
            if action.help is not None:field['help']=action.help
            fields.append(field)
        result[name]={'operation':name.replace('-','_'),'description':command.description or '', 'fields':fields,
                      'exclusive':[[a.dest for a in group._group_actions] for group in command._mutually_exclusive_groups]}
    return result


def tool_name(command):
    value=re.sub(r'([a-z0-9])([A-Z])',r'\1_\2',command).replace('-','_').lower()
    return 'astra_'+value


def field_schema(field):
    kind=field['type']
    result={'type':'integer' if field.get('integer') else 'number'} if kind=='number' else (
        {'type':'object'} if kind=='json' else {'type':kind})
    if 'choices' in field:result['enum']=field['choices']
    if 'default' in field:result['default']=field['default']
    if field.get('help'):result['description']=field['help']
    if field['array']:
        result={'type':'array','items':{k:v for k,v in result.items() if k!='default'},
                **({'default':field['default']} if 'default' in field else {})}
    return result


def parameters(name, command):
    fields=[f for f in command['fields'] if f['name'] not in {'request_id','pretty'}]
    if name in {'act','chain'}:
        result=copy.deepcopy(ACT_SCHEMA if name=='act' else CHAIN_SCHEMA)
        result['properties']['full']={'type':'boolean','description':'Request the full public response instead of the usual compact view.'}
        return result
    result=object_schema({f['name']:field_schema(f) for f in fields},
                         [f['name'] for f in fields if f['required'] and not f['optional']])
    if name=='knowledge':result['properties']['checkpoint']=copy.deepcopy(CHECKPOINT_SCHEMA)
    if name in {'evade','retreat'}:result['properties']['actions']=copy.deepcopy(CHAIN_SCHEMA['properties']['actions'])
    if name=='trigger':
        from astra_bridge.argument_specs import TRIGGERS
        result['properties']['name']['enum']=sorted(TRIGGERS)
    if name=='key':result['properties']['key']['enum']=['escape','enter','tab','space','up','down','left','right','backspace','delete','pageup','pagedown']
    exclusive=[{'not':{'required':[a,b]}} for group in command['exclusive']
               for i,a in enumerate(group) for b in group[i+1:]]
    if exclusive:result['allOf']=exclusive
    if name=='walk':result['oneOf']=[{'required':['ref'],'not':{'anyOf':[{'required':[k]} for k in ('x','y','observation')]}},
                                   {'required':['x','y','observation'],'not':{'required':['ref']}}]
    if name=='knowledge':
        for action,allowed in KNOWLEDGE_ACTION_FIELDS.items():
            forbidden=set(result['properties'])-allowed-{'full'}
            then={'not':{'anyOf':[{'required':[k]} for k in sorted(forbidden)]}}
            if action=='checkpoint':then['required']=['checkpoint']
            result.setdefault('allOf',[]).append({'if':{'properties':{'action':{'const':action}}},'then':then})
        result['allOf'].append({'if':{'properties':{'action':{'enum':['list','add','update','evidence','events','objects']}}},
                               'then':{'not':{'required':['checkpoint']}}})
    if name=='map':
        branches=[]
        for action,allowed in MAP_ARGUMENT_FIELDS.items():
            allowed=allowed|({'query','page','limit'} if action=='markers' else set())|{'action','full'}
            branch={'not':{'anyOf':[{'required':[k]} for k in sorted(set(result['properties'])-allowed)]}}
            if action is None:branch['not']['anyOf'].append({'required':['action']})
            else:branch.update(properties={'action':{'const':action}},required=['action'])
            if action=='zoom':branch['anyOf']=[{'required':['factor']},{'required':['fit']}]
            if action=='pan':branch['anyOf']=[{'required':['dx']},{'required':['dy']}]
            branches.append(branch)
        result['anyOf']=branches
    return result


def tools_catalog():
    commands=catalog()
    schemas={name:parameters(name,c) for name,c in commands.items() if name!='sequence'}
    steps=[]
    for op in sorted(SEQUENCE_OPS):
        name=next(name for name,c in commands.items() if c['operation']==op)
        schema=copy.deepcopy(schemas[name]);props=schema['properties'];props.pop('full',None)
        props['op']={'const':op};props['expect']=copy.deepcopy(EXPECT_SCHEMA)
        required=[k for k in schema.get('required',[]) if k!='full']
        if op in REF_OPS:
            props['select']=copy.deepcopy(SELECTOR_SCHEMA)
            source=source_for(op);props['select']['properties']['source']['enum']=[source]
            if source!='scene':
                props['select']['properties'].pop('actor_kind',None);props['select']['properties'].pop('nearest',None)
            props['bind']={'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_]*$'}
            schema['dependentRequired']={'bind':['select']}
            schema.setdefault('allOf',[]).append({'not':{'required':['ref','select']}})
            if 'ref' in required:
                required.remove('ref');schema.setdefault('allOf',[]).append({'anyOf':[{'required':['ref']},{'required':['select']}]})
        if op in {'use_item','select_spell','select_enchanted'}:
            props['name']={'type':'string','minLength':1}
            schema['allOf'].extend([{'not':{'required':['name','ref']}},{'not':{'required':['name','select']}}])
            for item in schema.get('allOf',[]):
                if 'anyOf' in item:item['anyOf'].append({'required':['name']})
        schema['required']=['op',*required];steps.append(schema)
    sequence=object_schema(copy.deepcopy(SEQUENCE_PROPERTIES),['actions'])
    sequence['properties']['actions']['items']={'anyOf':steps}
    sequence['properties']['full']={'type':'boolean'}
    schemas['sequence']=sequence
    tools=[]
    for name,c in commands.items():
        fields=[f for f in c['fields'] if f['name'] not in {'pretty','json'}]
        policy={'base_seconds':LONG_ACTION_TIMEOUT if c['operation'] in {'record_stop','finish_session'} else CLI_REQUEST_TIMEOUT}
        if c['operation'] in ACTION_DEFAULTS:policy.update(
            duration_field='max_seconds' if name in {'chain','sequence'} else 'seconds',
            default_duration=ACTION_DEFAULTS[c['operation']],duration_multiplier=ACTION_TIMEOUT_MULTIPLIER)
        tools.append({'name':tool_name(name),'description':c['description'],'input_schema':schemas[name],
            'invocation':{'argv':['game',name],'fields':fields,
                'json_payload':name in {'act','chain','sequence'},
                'request_id_option':next((f['options'][0] for f in c['fields'] if f['name']=='request_id'),None),
                'timeout':policy}})
    if len({t['name'] for t in tools})!=len(tools):raise ValueError('Tool names collide')
    if any(not t['description'] for t in tools):raise ValueError('Every game tool needs a description')
    return {'schema_version':1,'tools':tools}


if __name__=='__main__':
    import sys
    print(json.dumps(tools_catalog() if '--tools' in sys.argv else catalog(),indent=2))
