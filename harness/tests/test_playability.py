import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from astra_bridge.control import Control
from astra_bridge.protocol import BridgeError, validate
from astra_bridge.observations import compact, prune_screenshots, present_response
from astra_bridge.exploration import ExplorationAtlas
from astra_bridge.memory import SpatialMemory
from astra_bridge.workflows import validate_sequence, sequence, repair, read_document


def test_stop_and_status_bypass_active_action_and_preserve_its_result(tmp_path):
    started=threading.Event();results=[]
    s=SimpleNamespace(inbox=tmp_path/'inbox.json',session_id='session',latest_observation=None,
                      process=SimpleNamespace(poll=lambda:None),display=SimpleNamespace(name='test'),
                      uncertain=False,recorder=None)
    c=Control(s)
    def call(op,args):
        if op=='act':
            started.set();c.progress({'elapsed':1.2,'phase':'running'})
            assert c.cancelled.wait(2), 'stop was queued behind the action'
            return {'action':{'reason':'cancelled','elapsed':1.2,'motion':{'moved_m':3.1}}}
        assert op=='stop'
        return {'action':{'paused':True}}
    s.call=call
    worker=threading.Thread(target=lambda:results.append(c.execute('act',{'seconds':1000})))
    worker.start();assert started.wait(1)
    assert c.execute('status',{})['active_action']['elapsed']==1.2
    with pytest.raises(BridgeError,match='controller_busy'):c.execute('save',{'description':'no'})
    response=c.execute('stop',{});worker.join(1)
    assert json.loads((tmp_path/'cancel.json').read_text())['session']=='session'
    assert not worker.is_alive() and response['action']['paused']
    assert results[0]['action']['motion']['moved_m']==3.1
    assert c.status() is None


def test_screenshot_cache_preserves_explicit_notes_and_unrelated_files(tmp_path):
    memory=SpatialMemory(tmp_path/'memory.json')
    frames=[]
    for i in range(40):
        p=tmp_path/f'1234abcd-{i:06}.png';p.write_bytes(b'image');frames.append(p)
    memory.data['places']=[{'views':[{'screenshot':str(frames[0])}]}]
    unrelated=tmp_path/'user-picture.png';unrelated.write_bytes(b'user')
    for i in range(20):(tmp_path/f'1234abcd-{i:06}-atlas.svg').write_text('map')
    prune_screenshots(tmp_path,memory,8)
    assert frames[0].exists() and unrelated.exists()
    assert len(list(tmp_path.glob('1234abcd-*.png')))==9
    assert len(list(tmp_path.glob('*-atlas.svg')))==8


def test_compact_ui_preserves_all_dialogue_and_available_topics():
    text='Полный ответ. '*2000
    obs={'observation':1,'ui_mode':'Dialogue','ui':{'dialogue':{'text':text,'topics':[{'text':'Тема'}]},
          'elements':[{'role':'button','text':'Тема','ref':'ui_1','screen_visible':False,'enabled':True}]}}
    result=compact(obs)
    assert result['ui']['dialogue']['text']==text
    assert result['ui']['elements'][0]['ref']=='ui_1'


def enter(atlas,cell,visit,points):
    obs={'state':'running','ui_mode':'Gameplay','location':cell,'body':{'on_ground':True},
         'trajectory':{'ref':visit,'start_heading_deg':0,'samples':[
             {'sequence':i+1,'forward_m':p[1],'sideways_m':p[0],'vertical_m':p[2],'heading_deg':0}
             for i,p in enumerate(points)]}}
    atlas.ingest(obs,{'space':cell,'origin':[0,0,0]})
    atlas.annotate(obs)
    return obs


def test_named_atlas_routes_use_observed_directed_doors_and_survive_restart(tmp_path):
    path=tmp_path/'atlas.json';a=ExplorationAtlas(path)
    enter(a,'Outside','a',[[0,0,0]]);outside=a.anchor_node('Guild entrance')
    enter(a,'Inside','b',[[0,0,0]]);inside=a.anchor_node('Guild exit')
    a.add_transition(outside['ref'],inside['ref'],{'name':'Wooden door','description':'Guild'})
    enter(a,'Inside','b',[[0,.5,0],[0,1,0],[0,1.5,0],[0,2,0],[0,2.5,0],[0,3,0]])
    target=a.anchor_node('Library')
    # No invented reverse portal: it has not been traversed.
    assert a.route_to(outside['ref']) is None
    a.db.close();a=ExplorationAtlas(path)
    enter(a,'Outside','return-a',[[0,0,0]])
    plan=a.route_to(target['ref'])
    assert plan and [s['kind'] for s in plan['steps']]==['walk','door','walk']
    assert a.search('Library')['nodes'][0]['ref']==target['ref']
    # Map rendering is optional; semantic output works without an image tool.
    a.render=lambda *args:pytest.fail('an ordinary atlas request must not render files')
    assert a.present(None)['supported']


def test_known_long_path_and_separate_height_bands(tmp_path):
    a=ExplorationAtlas(tmp_path/'atlas.json')
    enter(a,'Road','road',[[0,0,0]]);origin=a.anchor_node('Start')
    points=[[0,i*.5,0] for i in range(601)]
    enter(a,'Road','road2',points)
    assert a.travelled_route(origin) is not None
    assert a.route_to(origin['ref'])['estimated_distance_m']==pytest.approx(300)
    enter(a,'Road','upper',[[0,300,4]])
    rows=a.present(None,radius=500)['levels']
    assert len(rows)==2
    assert a.search('Start',page=1,limit=1)['nodes']==[]


@pytest.mark.parametrize('op,args',[
    ('go',{'ref':'waypoint_x','seconds':300}),('move_local',{'forward_m':40,'seconds':60}),
    ('approach',{'ref':'visible_x','seconds':90}),('interact',{'ref':'visible_x','approach':True,'run':True,'seconds':60}),
    ('fly',{'forward_m':50,'seconds':60}),('chain',{'actions':[{'op':'wait','seconds':45}],'max_seconds':60}),
])
def test_explicit_budgets_are_not_small_fixed_caps(op,args):validate(op,args)


def test_sequences_validate_every_step_before_any_consumption():
    validate_sequence({'actions':[{'op':'use_item','name':'Potion'},{'op':'act','move':1,'seconds':10}]})
    for step in [{'op':'eval','code':'x'},{'op':'resetNPC','reason':'x'}, {'op':'use_item','name':'Potion','ref':'item_x'}]:
        with pytest.raises(BridgeError):validate_sequence({'actions':[{'op':'use_item','name':'Potion'},step]})


def test_compact_keeps_explicit_memory_views_and_requested_maps():
    place={'views':[{'observation':1,'screenshot':'a.png'}]}
    assert present_response(place)==place
    o=compact({'observation':2,'local_map':'floor.svg','exploration':{'svg':'atlas.svg','png':'atlas.png'}})
    assert o['local_map']=='floor.svg' and o['exploration']['png']=='atlas.png'


def test_door_spawn_gap_is_an_explicit_native_leg_not_a_missing_route(tmp_path):
    a=ExplorationAtlas(tmp_path/'atlas.json')
    enter(a,'Outside','a',[[0,0,0]]);target=a.anchor_node('Outside note')
    enter(a,'Outside','spawn',[[0,2,0]]);spawn=a.anchor_node()
    enter(a,'Inside','b',[[0,0,0]]);exit_node=a.anchor_node()
    a.add_transition(exit_node['ref'],spawn['ref'],{'name':'Exit'})
    plan=a.route_to(target['ref'])
    assert plan and plan['steps'][-1]=={'kind':'walk','ref':target['ref'],'source':'native_path_required'}


@pytest.mark.parametrize('after,reason',[
    ([{'panel':'repair','role':'item_slot','text':'hammer'}],'condition_met'),
    ([], 'repair_ui_closed'),
    ([{'panel':'repair','role':'item','text':'Sword','condition_current':85,'condition_max':100}], 'attempt_limit')])
def test_repair_uses_fresh_rows_and_never_claims_success_from_closed_ui(after,reason):
    snapshots=iter([{'elements':[{'panel':'repair','role':'item','text':'Sword','ref':'ui_1','enabled':True,
                                'condition_current':80,'condition_max':100}]},{'elements':after}])
    submitted=[]
    s=SimpleNamespace(control=SimpleNamespace(cancelled=threading.Event()),command=lambda op:next(snapshots),
                      call=lambda op,args:submitted.append(args) or {'feedback':{}},observe=lambda:{})
    result=repair(s,{'name':'Sword','attempts':1})
    assert submitted==[{'ref':'ui_1'}] and result['action']['reason']==reason
    assert result['feedback']['status']==('succeeded' if reason=='condition_met' else 'partial')


def test_read_all_pins_open_document_and_search_keeps_unicode_offsets():
    text='Straße. Вивек. '+('x'*8000)+' ВИВЕК'
    calls=[]
    def read(op,args):
        calls.append(args)
        if len(calls)>1:assert args['ref']=='document_open'
        offset=args.get('offset',0);limit=args.get('limit',4);end=min(len(text),offset+limit)
        return {'ref':'document_open','text':text[offset:end],'offset':offset,'next_offset':end,'eof':end==len(text)}
    s=SimpleNamespace(command=read,control=SimpleNamespace(cancelled=threading.Event()))
    assert read_document(s,{'all':True})['text']==text
    calls.clear();r=read_document(s,{'search':'вивек'})
    assert [m['offset'] for m in r['matches']]==[text.index('Вивек'),text.index('ВИВЕК')]


def test_sequence_stops_after_failure_without_repeating_consumables():
    calls=[];captures=[]
    o={'ui_mode':'Gameplay','stats':{'health':{'current':50,'maximum':100}}}
    def observe(**args):captures.append(args);return o
    def call(op,args):
        calls.append(op)
        return {'action':{'elapsed':1},'observation':o,'feedback':{'status':'failed','reason':'spell_failed'}}
    s=SimpleNamespace(observe=observe,call=call,control=SimpleNamespace(cancelled=threading.Event(),progress=lambda _:None))
    r=sequence(s,{'actions':[{'op':'cast','air':True},{'op':'use_item','ref':'item_should_not_be_consumed'}]})
    assert calls==['cast'] and r['action']['reason']=='spell_failed' and s.batch_depth==0
    assert captures==[{'capture':False},{}]
