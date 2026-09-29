import copy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from astra_bridge.doors import match_door
from astra_bridge.exploration import ExplorationAtlas
from astra_bridge.information import details, receipt_details
from astra_bridge.knowledge import Knowledge
from astra_bridge.memory import SpatialMemory
from astra_bridge.observations import present_response
from astra_bridge.protocol import BridgeError, check_result
from astra_bridge.receipts import Receipts
from astra_bridge.selectors import resolve_step, validate_step


def sight(key='private-instance-1', near=False, name='Фаргот', kind='actor'):
    row = {'ref':'visible_session_1','kind':kind,'distance_m':1 if near else 12,
           'details_visible':near,'_recognition_key':key,'in_reach':near}
    if kind=='actor': row['actor_kind']='npc'
    if near: row.update(name=name,name_source='observed')
    return row


def observation(row):
    return {'state':'running','scene':{'objects':[row]}}


def test_lua_inspection_and_private_identity():
    r=subprocess.run(['lua','tests/recognition.lua'],cwd=Path(__file__).parents[1],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr


def test_learn_only_on_inspection_and_keep_only_name(tmp_path):
    knowledge=Knowledge(tmp_path/'memory.sqlite3')
    assert 'name' not in knowledge.recognize(sight(), 'profile')
    near=sight(near=True,kind='door',name='Дом');near['description']='Locked 50'
    assert knowledge.recognize(near,'profile')['name_source']=='observed'
    far=sight(kind='door');far.update(name='Forbidden live rename',description='Unlocked')
    assert knowledge.recognize(far,'profile')['name']=='Дом'
    assert far['name_source']=='remembered' and 'description' not in far
    assert 'name' not in knowledge.recognize(sight(key='another',kind='door'),'profile')
    assert 'name' not in knowledge.recognize(sight(kind='door'),'another-profile')
    refreshed=sight(near=True,kind='door',name='Новое имя');refreshed['description']='Unlocked'
    knowledge.recognize(refreshed,'profile')
    assert knowledge.recognize(sight(kind='door'),'profile')['name']=='Новое имя'


def test_private_metadata_cannot_reach_responses_or_receipts(tmp_path):
    k=Knowledge(tmp_path/'memory.sqlite3')
    raw=observation(sight(near=True))
    raw['target_lock']=sight()
    with pytest.raises(BridgeError):check_result(copy.deepcopy(raw))
    public=k.recognize(raw,'profile')
    public['observation']=1
    assert public['target_lock']['name_source']=='remembered'
    for full in (False,True):
        assert '_recognition' not in json.dumps(present_response(public,full))
        assert 'private-instance' not in json.dumps(present_response(public,full))
    receipts=Receipts(tmp_path/'receipts.sqlite3')
    request,_=receipts.begin('observe',{},None)
    receipts.finish(request,public)
    assert '_recognition' not in json.dumps(receipts.get(request))
    session=SimpleNamespace(latest_observation=public)
    assert details(session,{'section':'scene'})['data']['objects'][0]['name']=='Фаргот'


def test_invalid_packet_never_teaches_a_name(tmp_path):
    k=Knowledge(tmp_path/'memory.sqlite3')
    raw=observation(sight(near=True));raw['secret_coordinate']=42
    with pytest.raises(BridgeError):k.recognize(raw,'profile')
    assert 'name' not in k.recognize(sight(),'profile')
    for bad in (None,[],1,'', 'x'*4097):
        row=sight();row['_recognition_key']=bad
        with pytest.raises(BridgeError):k.recognize(row,'profile')


def test_unknown_names_never_match_selectors_or_empty_doors(tmp_path):
    k=Knowledge(tmp_path/'memory.sqlite3')
    obs=k.recognize(observation(sight()),'profile')
    session=SimpleNamespace(observe=lambda **kwargs:obs)
    step={'op':'focus','select':{'name':'Фаргот'}}
    with pytest.raises(BridgeError,match='selection_unavailable'):resolve_step(session,step,{})
    step={'op':'focus','select':{'actor_kind':'npc','nearest':True}}
    validate_step(step,{})
    assert resolve_step(session,step,{})[0]['ref']=='visible_session_1'
    assert match_door([{'kind':'door','ref':'visible_door'}],{},[0,0,0],0)[0] is None
    k.recognize(sight(near=True),'profile')
    obs=k.recognize(observation(sight()),'profile')
    assert resolve_step(session,{'op':'focus','select':{'name':'Фаргот'}},{})[0]['ref']=='visible_session_1'


def test_unknown_objects_work_with_scan_details_memory_and_atlas(tmp_path):
    k=Knowledge(tmp_path/'memory.sqlite3')
    obs=k.recognize(observation(sight(kind='door')),'profile')
    obs.update(observation=1,location='Room',orientation={'heading_deg':0},
               ui_mode='Gameplay',body={'on_ground':True})
    memory=SpatialMemory(tmp_path/'places.json')
    assert memory.remember('Here','',[],'observed',obs)['visible_names']==[]
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    atlas.segment='test'
    atlas.data['segments']=[{'ref':'test','pose':[0,0,0],'nodes':[],'current_node':None,'heading':0,'location':'Room'}]
    assert atlas.annotate(obs)['landmarks']==[]
    raw={'views':[{'observation':obs}],'final':obs}
    summary=present_response(raw)
    landmark=summary['views'][0]['landmarks'][0]
    assert 'name' not in landmark and landmark['details_visible'] is False
    fetched=receipt_details({'response':raw},{'view':0,'section':'scene'})
    assert 'name' not in fetched['response']['data']['objects'][0]


def test_knowledge_uses_atlas_profile_across_load_restart_and_new_game(tmp_path):
    from test_exploration import anchored,sample
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    k=Knowledge(tmp_path/'memory.sqlite3')
    atlas.annotate(anchored(atlas,[sample(1)]))
    slot={'created':10,'description':'Before meeting','player_name':'P','player_level':1}
    atlas.checkpoint(slot)
    original=atlas.profile
    object_ref=k.recognize(sight(near=True),atlas.profile)['memory_ref']
    k.call({'action':'add','kind':'note','object_ref':object_ref,'text':'Met after this save'},atlas.profile)
    atlas.restore(slot)  # Older save keeps names learned afterwards, just like routes.
    assert k.recognize(sight(),atlas.profile)['name']=='Фаргот'
    assert k.call({'action':'list','object_ref':object_ref},atlas.profile)['items'][0]['text']=='Met after this save'
    k.db.close();k=Knowledge(tmp_path/'memory.sqlite3')
    restarted=ExplorationAtlas(tmp_path/'atlas.json')
    assert k.recognize(sight(),restarted.profile)['name']=='Фаргот'
    assert k.call({'action':'list','object_ref':object_ref},restarted.profile)['total']==1
    restarted.new_game()
    assert restarted.profile!=original and 'name' not in k.recognize(sight(),restarted.profile)
    restarted.restore(slot)
    assert k.recognize(sight(),restarted.profile)['name']=='Фаргот'


def test_object_notes_work_before_identification_without_revealing_a_name(tmp_path):
    k=Knowledge(tmp_path/'memory.sqlite3')
    unknown=k.recognize(sight(),'profile')
    memory_ref=unknown['memory_ref']
    assert memory_ref.startswith('object_') and 'name' not in unknown
    note=k.call({'action':'add','kind':'note','object_ref':memory_ref,'text':'Person near the stairs'},'profile')
    assert note['object_ref']==memory_ref and note['source']=='agent_note'
    assert 'name' not in k.recognize(sight(),'profile')
    assert k.call({'action':'list','object_ref':memory_ref},'profile')['items'][0]['text']=='Person near the stairs'
    objects=k.call({'action':'objects','object_ref':memory_ref},'profile')
    assert objects['historical'] and objects['objects'][0]['notes_total']==1
    assert 'name' not in objects['objects'][0]
    identified=k.recognize(sight(near=True),'profile')
    assert identified['memory_ref']==memory_ref
    assert k.call({'action':'objects','query':'Фаргот'},'profile')['objects'][0]['ref']==memory_ref
    assert 'private-instance' not in json.dumps(k.call({'action':'objects'},'profile'))


def test_notes_are_per_instance_and_profile_and_survive_restart(tmp_path):
    path=tmp_path/'memory.sqlite3'
    k=Knowledge(path)
    first=k.recognize(sight(near=True),'profile')['memory_ref']
    other=k.recognize(sight(key='another',near=True),'profile')['memory_ref']
    note=k.call({'action':'add','kind':'conversation','object_ref':first,'text':'Ask about the ring'},'profile')
    assert k.call({'action':'list','object_ref':other},'profile')['total']==0
    k.db.close();k=Knowledge(path)
    assert k.recognize(sight(),'profile')['memory_ref']==first
    assert k.call({'action':'list','object_ref':first},'profile')['total']==1
    assert k.call({'action':'objects'},'new-profile')['total']==0
    assert k.call({'action':'list'},'new-profile')['total']==0
    for args in ({'action':'list','object_ref':first},
                 {'action':'add','object_ref':first,'text':'wrong profile'},
                 {'action':'update','ref':note['ref'],'status':'done'}):
        with pytest.raises(BridgeError,match='unknown_object_memory'):k.call(args,'new-profile')
    k.call({'action':'update','ref':note['ref'],'status':'done'},'profile')
    assert k.call({'action':'list','object_ref':first},'profile')['items'][0]['status']=='done'
    with pytest.raises(BridgeError,match='unknown_object_memory'):
        k.call({'action':'add','object_ref':'visible_session_1','text':'wrong handle'},'profile')
    with pytest.raises(BridgeError,match='observed_evidence_quote_required'):
        k.call({'action':'add','kind':'fact','object_ref':first,'text':'Unsupported claim'},'profile')


def test_existing_memory_migration_keeps_general_notes_and_evidence(tmp_path):
    import sqlite3
    path=tmp_path/'old.sqlite3'
    db=sqlite3.connect(path)
    db.executescript('''CREATE TABLE notes(ref TEXT PRIMARY KEY,kind TEXT,text TEXT,status TEXT,evidence TEXT,created REAL);
        INSERT INTO notes VALUES ('note_old','task','Old task','open',NULL,0);
        CREATE TABLE evidence(ref TEXT PRIMARY KEY,kind TEXT,title TEXT,text TEXT,created REAL);
        INSERT INTO evidence VALUES ('evidence_old','dialogue','Old speaker','Old dialogue',0);
        CREATE TABLE recognized_objects(profile TEXT,object_key TEXT,name TEXT,kind TEXT,actor_kind TEXT,first_seen REAL,last_seen REAL,
            PRIMARY KEY(profile,object_key));
        INSERT INTO recognized_objects VALUES ('profile','old-key','Old NPC','actor','npc',0,0);''')
    db.commit();db.close()
    k=Knowledge(path)
    assert k.call({'action':'list'})['items'][0]['text']=='Old task'
    assert k.call({'action':'evidence','ref':'evidence_old'})['text']=='Old dialogue'
    old=k.call({'action':'objects'},'profile')['objects'][0]
    assert old['name']=='Old NPC' and old['ref'].startswith('object_')
    k.db.close();k=Knowledge(path)
    assert k.call({'action':'objects'},'profile')['objects'][0]['ref']==old['ref']
