import base64
import json
import os
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from astra_bridge.cli import build_parser
from astrabridge_runner.bridge import BridgeFailure, invocation, tool_timeout
from astrabridge_runner.resources import Resources, ResourceFailure
from astrabridge_runner.history import History
from astrabridge_runner.providers.deepseek import DeepSeek
from astrabridge_runner.types import Reply, ToolCall


def calls(f):return [json.loads(line) for line in (f['root']/'calls.jsonl').read_text().splitlines()]


@pytest.mark.parametrize('command,args',[
    ('comment',{'text':'--config'}),('comment',{'text':'--help'}),
    ('interact',{'ref':'visible_1','adjust_viewpoint':False,'run':True}),
    ('knowledge',{'action':'checkpoint','checkpoint':{'goal':'x','next_step':'y'}}),
    ('act',{'move':1,'seconds':.2,'full':True}),
    ('chain',{'actions':[{'op':'strike'},{'op':'wait','seconds':.2}]}),
    ('sequence',{'actions':[{'op':'move_local','forward_m':1}]}),
    ('remember',{'label':'quotes " ; $() кириллица','exits':['--config','Left'],'confidence':'observed'}),
    ('map',{'action':'zoom','fit':True}),
])
def test_exported_invocation_roundtrips_existing_parser(fixture,command,args):
    tool=next(t for t in fixture['tools']['tools'] if t['invocation']['argv'][1]==command)
    Draft202012Validator(tool['input_schema']).validate(args)
    argv=invocation(tool,args,'request')
    actual=vars(build_parser().parse_args(argv[1:]));actual.pop('command');actual.pop('request_id',None)
    if tool['invocation']['json_payload']:
        actual={**json.loads(actual.pop('json')),**actual}
    for name,value in args.items():assert actual[name]==value


def test_catalog_validation_errors_and_unknown_tools_have_no_execution(fixture,monkeypatch):
    f=fixture;b=f['bridge'];b.load_tools();before=len(calls(f))
    assert b.call('run_shell','{"command":"bad"}','call')['error']=='unknown_tool'
    assert b.call('astra_act','{"move":2}','call')['error']=='invalid_tool_arguments'
    assert b.call('astra_act','{"move":NaN}','call')['error']=='invalid_tool_arguments'
    assert len(calls(f))==before
    monkeypatch.setenv('DEEPSEEK_API_KEY','secret-test-key')
    # A fresh bridge strips the key from all spawned child processes.
    from astrabridge_runner.bridge import Bridge
    child=Bridge(f['skill'],f['journal']);child.load_tools();child.connect();child.call('astra_act','{"move":1,"seconds":0.2}','call');child.disconnect()
    assert not any(c['has_key'] for c in calls(f))


def test_timeout_and_invalid_stdout_report_unknown_result_without_retry(fixture):
    f=fixture;b=f['bridge'];b.load_tools()
    bad=deepcopy(b.tools['astra_act']);bad['invocation']['argv']=['game','bad'];b.tools['astra_act']=bad
    result=b.call('astra_act','{}','bad');assert result['error']=='invalid_tool_response' and result['result_unknown']
    slow=deepcopy(bad);slow['invocation']['argv']=['game','slow'];slow['invocation']['timeout']={'base_seconds':.1};b.tools['astra_act']=slow
    result=b.call('astra_act','{}','slow');assert result['error']=='tool_result_unknown'
    assert sum(c['args'][1:2]==['slow'] for c in calls(f))==1
    assert 'partial JSON' in (f['journal'].root/'events.jsonl').read_text()


def test_time_budgets_come_from_bridge_not_a_short_global_timeout(fixture):
    act=next(t for t in fixture['tools']['tools'] if t['name']=='astra_act')
    assert tool_timeout(act,{'seconds':900})>900
    finish=next(t for t in fixture['tools']['tools'] if t['name']=='astra_finish_session')
    assert tool_timeout(finish,{})>=600


def test_images_are_archived_before_source_cleanup_and_only_latest_is_sent(fixture):
    f=fixture;b=f['bridge'];b.load_tools();b.connect();r=Resources(f['skill'],f['journal'])
    history=History(DeepSeek('secret-test-key',f['journal']),'rules',f['journal'],r,image_limit=1)
    history.assistant(Reply([{'role':'assistant','content':None,'reasoning_content':'reasoning retained','tool_calls':[]}],''),[])
    refs=[]
    for i in range(2):
        result=b.call('astra_observe','{}',f'call{i}')
        result,ref=r.collect(result,b.image_roots,f'call{i}');refs.append(ref)
        history.tool(ToolCall(f'call{i}','astra_observe','{}'),result,ref)
    assert len(refs)==2 and refs[0]!=refs[1]
    for p in (f['storage']/'exports/default').glob('*.png'):p.unlink()
    payload=history.payload();images=[part for m in payload if isinstance(m['content'],list) for part in m['content'] if part['type']=='image_url']
    assert len(images)==1 and len([m for m in payload if m['role']=='tool'])==2
    assert payload[0]['reasoning_content']=='reasoning retained'
    old,_=r.saved_image(refs[0]);history.tool(ToolCall('old','view_saved_image','{}'),old,refs[0],True)
    selected=[part for m in history.payload() if isinstance(m['content'],list) for part in m['content'] if part['type']=='image_url']
    assert len(selected)==1
    data=base64.b64decode(selected[0]['image_url']['url'].split(',',1)[1])
    assert data==(f['journal'].root/'images'/r.images[refs[0]]['sha256']).with_suffix('.png').read_bytes()
    assert 'Historical' in history.messages[-1]['content'][0]['text']


def test_resource_tools_do_not_read_arbitrary_files(fixture):
    f=fixture;r=Resources(f['skill'],f['journal'])
    assert 'Navigation' in r.read_reference('navigation')['result']['text']
    for ref in ('../installation','/etc/passwd','installation.json'):
        with pytest.raises(ResourceFailure):r.read_reference(ref)
        with pytest.raises(ResourceFailure):r.saved_image(ref)
    private=f['root']/'private.png';private.write_bytes(b'\x89PNG\r\n\x1a\n')
    with pytest.raises(ResourceFailure):r.register(private,[f['storage']/'exports/default'],'call')


def test_scan_registers_views_and_selects_final_without_duplicate_images(fixture):
    f=fixture;b=f['bridge'];b.load_tools();b.connect();r=Resources(f['skill'],f['journal'])
    observations=[b.call('astra_observe','{}',f'c{i}')['result'] for i in range(4)]
    result={'ok':True,'result':{'views':[{'observation':o} for o in observations],'final':observations[-1]}}
    augmented,ref=r.collect(result,b.image_roots,'scan')
    assert len(augmented['image_refs'])==4 and ref==augmented['image_refs'][-1]['image_ref']


def test_images_quoted_in_memory_do_not_silently_replace_the_current_view(fixture):
    f=fixture;b=f['bridge'];b.load_tools();b.connect();r=Resources(f['skill'],f['journal'])
    observation=b.call('astra_observe','{}','old')['result']
    remembered={'ok':True,'result':{'places':[{'views':[observation]}]}}
    result,selected=r.collect(remembered,b.image_roots,'recall')
    assert selected is None and len(result['image_refs'])==1
    assert not result['image_refs'][0]['selected']
