"""Documentation examples use the actual public validators and sequence runner."""
import copy
import json
from pathlib import Path
import re
import shlex
import threading
from types import SimpleNamespace

import pytest
from astra_bridge.workflows import sequence, validate_sequence

SKILL=Path(__file__).resolve().parents[2]/'skill'


def examples():
    return [json.loads(shlex.split(line)[3]) for line in (SKILL/'references/sequences.md').read_text().splitlines()
            if line.startswith('astrabridge game sequence ')]


def test_all_documented_sequences_match_the_public_interface():
    for args in examples():validate_sequence(args)


def run_example(args, change):
    state={'ui_mode':'Gameplay','location':'Town','simulation_seconds':0,
           'stats':{'health':{'current':50,'maximum':50}},'inventory':0}
    calls=[]
    def observe(**_):return copy.deepcopy({k:v for k,v in state.items() if k!='inventory'})
    def command(op,args=None):
        if op=='ui':return {'elements':[{'ref':'ui_current','control':'service_barter','enabled':True}]}
        assert op=='inspect' and args['view']=='inventory'
        return {'items':[{'name':'OBSERVED_ITEM_NAME','count':state['inventory']}]}
    def call(op,params):
        calls.append(op);action={'elapsed':.1};feedback={'status':'succeeded'}
        change(op,state,action,feedback)
        return {'action':action,'feedback':feedback,'observation':observe()}
    s=SimpleNamespace(observe=observe,command=command,call=call,
       control=SimpleNamespace(cancelled=threading.Event(),progress=lambda _:None))
    return sequence(s,args),calls,state


@pytest.mark.parametrize('failure',['timeout','damage','modal'])
def test_wait_return_example_stops_before_navigation(failure):
    args=next(a for a in examples() if a['actions'][0]['op']=='wait_until')
    def change(op,state,action,feedback):
        if failure=='timeout':feedback.update(status='partial',reason='condition_timeout')
        elif failure=='damage':state['stats']['health']['current']=45
        else:state['ui']={'modal':True}
    r,calls,_=run_example(args,change)
    assert calls==['wait_until']
    assert r['action']['reason']=={'timeout':'condition_timeout','damage':'player_hurt','modal':'ui_input_required'}[failure]


@pytest.mark.parametrize('menu',['Barter','Dialogue'])
def test_service_example_requires_expected_menu_before_buying(menu):
    args=next(a for a in examples() if a['actions'][0]['op']=='choose')
    def change(op,state,action,feedback):state['ui_mode']=menu
    r,calls,_=run_example(args,change)
    assert calls==(['choose','buy'] if menu=='Barter' else ['choose'])
    assert r['action']['reason']==('completed' if menu=='Barter' else 'expectation_failed')


@pytest.mark.parametrize('received',[0,1])
def test_pickup_example_checks_inventory_and_never_repeats_the_interaction(received):
    args=next(a for a in examples() if a['actions'][0]['op']=='interact')
    def change(op,state,action,feedback):state['inventory']+=received
    r,calls,state=run_example(args,change)
    assert calls==['interact'] and state['inventory']==received
    assert r['action']['reason']==('completed' if received else 'expectation_failed')


def test_skill_links_resolve_after_reference_split():
    def headings(path):
        # GitHub heading anchors, including punctuation removal for code spans.
        return {re.sub(r'[^\w\- ]','',h.lower()).replace(' ','-') for h in
                re.findall(r'^#{1,6}\s+(.+)$',path.read_text(),re.M)}
    for path in SKILL.rglob('*.md'):
        for link in re.findall(r'\[[^\]]*\]\(([^)]+)\)',path.read_text()):
            if '://' in link:continue
            file,_,anchor=link.partition('#');target=(path.parent/file).resolve() if file else path
            assert target.is_file(),(path,link)
            if anchor:assert anchor in headings(target),(path,link)
