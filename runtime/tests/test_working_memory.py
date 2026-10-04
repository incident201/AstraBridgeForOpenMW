import copy
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from astra_bridge.knowledge import Knowledge
from astra_bridge.memory import SpatialMemory
from astra_bridge.exploration import ExplorationAtlas
from astra_bridge.session import Session
from astra_bridge.observations import compact
from astra_bridge.protocol import BridgeError
from astra_bridge.cli import build_parser
from astra_daemon.runtime import Runtime


def memory_session(tmp_path):
    s=Session.__new__(Session)
    s.lock=threading.RLock()
    s.memory=SpatialMemory(tmp_path/'spatial.json')
    s.atlas=ExplorationAtlas(tmp_path/'atlas.json')
    s.knowledge=Knowledge(tmp_path/'knowledge.sqlite3')
    return s


def checkpoint(s, **values):
    return s.call('knowledge',{'action':'checkpoint','checkpoint':{
        'goal':'Find the house described by the guide',
        'next_step':'Inspect the remaining doors near the verified landmark',**values}})


def brief(s):return s.call('knowledge',{'action':'brief'})


def test_replace_resume_and_load_revalidation_preserve_notes(tmp_path):
    s=memory_session(tmp_path)
    assert brief(s)['checkpoint'] is None
    assert s.working_memory_hint()=={'available':False}
    note=s.call('knowledge',{'action':'add','kind':'task','text':'Earlier objective'})
    s.call('knowledge',{'action':'update','ref':note['ref'],'status':'done'})
    checkpoint(s,note_refs=[note['ref']],failed_attempts=['Repeated the same circuit without finding a new door'])
    first=brief(s)
    assert first['working_memory']=={'available':True,'revision':1,'needs_revalidation':False}
    checkpoint(s,goal='Ask a different observed NPC',next_step='Approach the person by the bridge')
    assert s.knowledge.db.execute('SELECT COUNT(*) FROM working_checkpoints').fetchone()[0]==1
    assert brief(s)['working_memory']['revision']==2
    s.knowledge.db.close();s.atlas.db.close()
    resumed=memory_session(tmp_path)
    assert brief(resumed)['checkpoint']['goal']=='Ask a different observed NPC'
    assert not resumed.working_memory_hint()['needs_revalidation']
    resumed.memory.branch('load')
    stale=brief(resumed)
    assert stale['working_memory']['needs_revalidation'] and stale['revalidation_reason']=='load'
    assert brief(resumed)==stale, 'reading is not acknowledgement'
    assert resumed.call('knowledge',{'action':'list'})['items'][0]['status']=='done'
    checkpoint(resumed,status='done',next_step='')
    assert not resumed.working_memory_hint()['needs_revalidation']
    assert brief(resumed)['checkpoint']['status']=='done'


def test_reference_validation_is_atomic_and_does_not_disclose_private_state(tmp_path):
    s=memory_session(tmp_path)
    evidence=s.knowledge.capture('dialogue','Guide','Go north to the bridge. '+'long '*300)
    seen={'scene':{'objects':[{'ref':'visible_test','kind':'door','_recognition_key':'private_engine_key',
                             'details_visible':True,'name':'Observed door','description':'Locked'}]}}
    s.knowledge.recognize(seen,s.atlas.profile);obj=seen['scene']['objects'][0]['memory_ref']
    note=s.call('knowledge',{'action':'add','kind':'note','text':'Try after returning','object_ref':obj})
    s.atlas.data['segments']=[{'ref':'visited','profile':s.atlas.profile,'location':'Town','nodes':[
        {'ref':'node_visited_A1','label':'A1','p':[123,456,789],'motor_ref':'waypoint_secret','names':['Door']}]}]
    checkpoint(s,evidence_refs=[evidence],note_refs=[note['ref']],object_refs=[obj],place_refs=['node_visited_A1'])
    result=brief(s)
    assert result['references']['objects'][0]['name']=='Observed door'
    assert result['references']['notes'][0]['object_ref']==obj
    assert len(result['references']['evidence'][0]['excerpt'])==160
    serialized=json.dumps(result)
    assert all(secret not in serialized for secret in ['private_engine_key','waypoint_secret','123','Locked'])
    for values in [{'evidence_refs':['evidence_missing']},{'note_refs':['note_missing']},{'object_refs':['object_missing']},
                   {'place_refs':['node_missing']},{'place_refs':['waypoint_secret']},{'object_refs':['visible_test']}]:
        with pytest.raises(BridgeError):checkpoint(s,**values)
        assert brief(s)==result
    with s.knowledge.db:s.knowledge.db.execute('DELETE FROM evidence WHERE ref=?',(evidence,))
    assert brief(s)['references']['evidence']==[{'ref':evidence,'unavailable':True}]


@pytest.mark.parametrize('payload',[None,[],{}, {'goal':'x','next_step':'x','status':[]},
    {'goal':'','next_step':'x'},{'goal':'x','next_step':''},{'goal':'x','next_step':'x','hidden':True},
    {'goal':'x','next_step':'x','object_refs':[[]]}, {'goal':'x','next_step':'x','failed_attempts':['']},
    {'goal':'x','next_step':'x','failed_attempts':['x']*9},
    {'goal':'я'*2000,'next_step':'я'*2000,'failed_attempts':['я'*600]}])
def test_invalid_or_unbounded_checkpoints_do_not_replace_state(tmp_path,payload):
    s=memory_session(tmp_path);checkpoint(s);before=brief(s)
    with pytest.raises(BridgeError):s.call('knowledge',{'action':'checkpoint','checkpoint':payload})
    assert brief(s)==before
    with pytest.raises(BridgeError):s.call('knowledge',{'action':'brief','checkpoint':{}})


def test_new_atlas_namespace_cannot_read_previous_checkpoint_or_object_links(tmp_path):
    s=memory_session(tmp_path);old=s.atlas.profile
    seen={'ref':'visible_actor','kind':'actor','actor_kind':'npc','_recognition_key':'secret','details_visible':True,'name':'Known NPC'}
    s.knowledge.recognize(seen,old);obj=seen['memory_ref']
    note=s.call('knowledge',{'action':'add','text':'Earlier task','object_ref':obj})
    checkpoint(s,object_refs=[obj]);s.atlas.new_game();s.memory.branch('new_game')
    assert brief(s)['checkpoint'] is None
    for values in [{'object_refs':[obj]},{'note_refs':[note['ref']]}]:
        with pytest.raises(BridgeError,match='unknown_object_memory'):checkpoint(s,**values)
    s.atlas.profile=old
    assert brief(s)['working_memory']['needs_revalidation']


@pytest.mark.asyncio
async def test_desktop_profiles_are_empty_or_explicit_independent_copies(tmp_path):
    r=Runtime(tmp_path/'installation',tmp_path/'state',tmp_path/'game')
    original=r.root;s=memory_session(original/'atlas');checkpoint(s)
    s.knowledge.db.close();s.atlas.db.close()
    copied=await r.profile_operation('duplicate',{'id':'default','name':'Copied'})
    clone=memory_session(r.profiles.path(copied['result']['id'])/'atlas')
    assert brief(clone)['working_memory']['revision']==1
    checkpoint(clone,goal='Independent goal')
    original_session=memory_session(original/'atlas')
    assert brief(original_session)['checkpoint']['goal']!='Independent goal'
    created=await r.profile_operation('create',{'name':'Empty'})
    empty=memory_session(r.profiles.path(created['result']['id'])/'atlas')
    assert brief(empty)['checkpoint'] is None
    for session in (clone,original_session,empty):session.knowledge.db.close();session.atlas.db.close()
    await r.close()


@pytest.mark.asyncio
async def test_connect_returns_only_hint_and_observation_compaction_keeps_it(tmp_path):
    r=Runtime(tmp_path/'installation',tmp_path/'state',tmp_path/'game')
    s=memory_session(r.root/'atlas');checkpoint(s)
    s.process=SimpleNamespace(poll=lambda:None);r.session=s
    s.timeline=SimpleNamespace(agent=lambda connected:None)
    r._mode=lambda _:None
    result=await r.acquire_agent('Agent')
    assert result['working_memory']==s.working_memory_hint()
    assert 'Find the house' not in json.dumps(result)
    obs=compact({'observation':1,'working_memory':s.working_memory_hint()})
    assert obs['working_memory']==result['working_memory']
    r.session=None;s.knowledge.db.close();s.atlas.db.close();await r.close()


def test_python_cli_decodes_checkpoint_as_a_nested_payload():
    args=vars(build_parser().parse_args(['knowledge','checkpoint','{"goal":"Continue","next_step":"Observe"}']))
    assert args['action']=='checkpoint' and args['checkpoint']['next_step']=='Observe'
    assert vars(build_parser().parse_args(['knowledge','brief']))['checkpoint'] is None


def test_additive_migration_retains_legacy_evidence_and_note_status(tmp_path):
    import sqlite3
    path=tmp_path/'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE notes (ref TEXT PRIMARY KEY,kind TEXT,text TEXT,status TEXT,evidence TEXT,created REAL);'
                         'CREATE TABLE evidence (ref TEXT PRIMARY KEY,kind TEXT,title TEXT,text TEXT,created REAL);')
        db.execute('INSERT INTO notes VALUES (?,?,?,?,?,?)',('note_old','task','Original task','done',None,0))
        db.execute('INSERT INTO evidence VALUES (?,?,?,?,?)',('evidence_old','journal','Journal','Observed text',0))
    k=Knowledge(path)
    k.call({'action':'checkpoint','checkpoint':{'goal':'Continue','next_step':'Verify current journal',
        'note_refs':['note_old'],'evidence_refs':['evidence_old']}},'profile',branch='branch')
    assert k.call({'action':'list'},'profile')['items'][0]['status']=='done'
    assert k.call({'action':'evidence','ref':'evidence_old'},'profile')['text']=='Observed text'
    k.db.close()
