import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from astra_daemon.commands import catalog, tools_catalog, tool_name
from astra_daemon.api_skill import build_api_skill
from astra_bridge.protocol import validate, BridgeError
from astra_bridge.workflows import validate_sequence


def test_api_skill_build_preserves_unicode_with_an_ascii_host_locale(tmp_path):
    source=Path(__file__).resolve().parents[2]/'skill'
    subprocess.run([sys.executable,'-m','astra_daemon.api_skill',str(source),str(tmp_path/'skill')],
                   env={**os.environ,'LC_ALL':'C','PYTHONUTF8':'0','PYTHONCOERCECLOCALE':'0'},
                   check=True,capture_output=True)
    assert 'Observe → act → verify → remember' in (tmp_path/'skill/SKILL.md').read_text(encoding='utf-8')


def test_export_is_complete_described_and_independent_of_game_state():
    commands=catalog();tools=tools_catalog()
    assert tools['schema_version']==1
    assert len(tools['tools'])==len(commands)
    assert len({t['name'] for t in tools['tools']})==len(commands)
    for tool in tools['tools']:
        Draft202012Validator.check_schema(tool['input_schema'])
        name=tool['invocation']['argv'][1]
        assert tool['name']==tool_name(name) and tool['description']==commands[name]['description']
        assert tool['description'] and tool['invocation']['argv'][0]=='game'
        assert 'pretty' not in tool['input_schema']['properties'] and 'request_id' not in tool['input_schema']['properties']
    assert not any(t['invocation']['argv'][1] in ('start','serve','shutdown','restart','version') for t in tools['tools'])


@pytest.mark.parametrize('name,args',[
    ('act',{'move':1,'seconds':.2}),('chain',{'actions':[{'op':'strike'},{'op':'wait','seconds':.2}]}),
    ('sequence',{'actions':[{'op':'act','move':1,'seconds':.1,'expect':{'min_horizontal_displacement_m':.05}}]}),
    ('sequence',{'actions':[{'op':'approach','select':{'source':'scene','kind':'actor','nearest':True},'bind':'npc'}]}),
    ('knowledge',{'action':'checkpoint','checkpoint':{'goal':'Reach an observed door','next_step':'Observe'}}),
])
def test_structured_schemas_accept_normal_existing_payloads(name,args):
    tool=next(t for t in tools_catalog()['tools'] if t['invocation']['argv'][1]==name)
    Draft202012Validator(tool['input_schema']).validate(args)
    if name in ('act','chain'):validate(name,args)
    if name=='sequence':validate_sequence(args)


@pytest.mark.parametrize('name,args',[
    ('act',{'move':2}),('act',{'position':[1,2,3]}),('chain',{'actions':[{'op':'eval','code':'bad'}]}),
    ('sequence',{'actions':[{'op':'eval','code':'bad'}]}),
    ('knowledge',{'action':'checkpoint','checkpoint':{'goal':'x','next_step':'y','private_path':'secret'}}),
])
def test_native_tool_schemas_reject_wrong_types_and_hidden_operations(name,args):
    tool=next(t for t in tools_catalog()['tools'] if t['invocation']['argv'][1]==name)
    assert not Draft202012Validator(tool['input_schema']).is_valid(args)


def test_api_skill_reuses_rules_and_has_native_instructions(tmp_path):
    source=Path(__file__).resolve().parents[2]/'skill'
    build_api_skill(source,tmp_path/'skill')
    root=tmp_path/'skill';main=(root/'SKILL.md').read_text()
    assert 'navmesh.db' in main and 'no game console' in main.lower()
    assert 'view_saved_image' in main and 'read_skill_reference' in main
    onboarding=(root/'references/onboarding.md').read_text()
    assert 'controls, or a tutorial/confirmation popup.' in onboarding
    assert 'astra_wait_until(condition="controls", seconds=30)' in onboarding
    assert 'astra_act({"seconds":10})' in onboarding
    for path in root.rglob('*.md'):
        text=path.read_text()
        assert 'astrabridge game' not in text and '```sh' not in text and 'stdout' not in text
        assert not re.search(r'--[a-z]',text)
        for link in re.findall(r'\[[^\]]*\]\(([^)]+)\)',text):
            if '://' in link:continue
            file,_,anchor=link.partition('#');target=(path.parent/file).resolve() if file else path
            assert target.is_file(),(path,link)
            if anchor:
                headings={re.sub(r'[^\w\- ]','',h.lower()).replace(' ','-') for h in re.findall(r'^#{1,6}\s+(.+)$',target.read_text(),re.M)}
                assert anchor in headings,(path,link)


def test_native_skill_examples_preserve_literal_strings_and_checkpoint_arguments():
    import ast
    from astra_daemon.api_skill import tool_prose
    checkpoint={'goal':'Reach the known door','next_step':'Observe','evidence_refs':[]}
    examples=[('comment "I will inspect [the door] and [ACTOR_REF]."', 'astra_comment', {'text':'I will inspect [the door] and [ACTOR_REF].'}),
              ("knowledge checkpoint '"+json.dumps(checkpoint)+"'", 'astra_knowledge',
               {'action':'checkpoint','checkpoint':checkpoint})]
    schemas={tool['name']:tool['input_schema'] for tool in tools_catalog()['tools']}
    for source,name,expected in examples:
        rendered=tool_prose('`'+source+'`').strip().strip('`')
        call=ast.parse(rendered,mode='eval').body
        actual={kw.arg:json.loads(ast.get_source_segment(rendered,kw.value)) for kw in call.keywords}
        assert call.func.id==name and actual==expected
        Draft202012Validator(schemas[name]).validate(actual)


def test_native_skill_keeps_json_field_names_and_optional_arguments_distinct():
    from astra_daemon.api_skill import tool_prose
    rendered=tool_prose('| JSON field | Meaning |\n|---|---|\n'
                        '| `trigger` | Use `trigger Inventory` to open the menu. |\n\n'
                        '`strike [ACTOR_REF] --charge 0.8`\n')
    assert '| `trigger` |' in rendered
    assert '`astra_trigger(name="Inventory")`' in rendered
    assert '`astra_strike(charge=0.8)`' in rendered
