"""One command catalog shared by the Python Game API and the packaged TS CLI."""
import argparse
import json
from pathlib import Path

from astra_bridge.cli import build_parser

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


if __name__=='__main__':
    print(json.dumps(catalog(),indent=2))
