from pathlib import Path
import json
import subprocess
import threading
from types import SimpleNamespace

import pytest

from astra_bridge.autosave import Autosave, finish_session
from astra_bridge.control import Control
from astra_bridge.information import details, query_ui
from astra_bridge.knowledge import Knowledge
from astra_bridge.observations import compact, present_response
from astra_bridge.protocol import BridgeError
from astra_bridge.receipts import Receipts
from astra_bridge.exploration import ExplorationAtlas
from astra_bridge.feedback import feedback


def test_receipt_survives_disconnect_restart_and_never_replays(tmp_path):
    calls=[]
    session=SimpleNamespace(inbox=tmp_path/'inbox.json',runtime=tmp_path,latest_observation=None,uncertain=False,
                            call=lambda op,args:calls.append(op) or {'action':{'submitted':True}})
    control=Control(session)
    result=control.execute('use_item',{'ref':'item_1','request_id':'consume-once'})
    assert result['request_id']=='consume-once'
    restarted=Control(session)
    cached=restarted.execute('use_item',{'ref':'item_1','request_id':'consume-once'})
    assert cached['response']['action']['submitted'] and not cached['replayed']
    assert calls==['use_item']
    with pytest.raises(BridgeError,match='request_id_conflict'):
        restarted.execute('use_item',{'ref':'item_2','request_id':'consume-once'})


def test_inflight_receipt_after_controller_crash_is_unknown(tmp_path):
    store=Receipts(tmp_path/'receipts.db');store.begin('cast',{},'maybe-consumed')
    store.db.close()
    recovered=Receipts(tmp_path/'receipts.db')
    assert recovered.get('maybe-consumed')['status']=='unknown'
    assert recovered.begin('cast',{},'maybe-consumed')[1]['status']=='unknown'


def test_progress_keeps_outer_sequence_and_child_separate(tmp_path):
    control=Control(SimpleNamespace(inbox=tmp_path/'inbox.json'))
    control.active={'operation':'sequence','started':0}
    control.progress({'operation':'cast','elapsed':1})
    assert control.active['operation']=='sequence' and control.active['step_operation']=='cast'


def test_compact_keeps_critical_equipment_effect_time_and_access_to_complete_ui():
    text='Evidence sentence. '*2000
    observation={'observation':4,'state':'running','ui_mode':'Dialogue','ui':{'revision':'abc',
        'dialogue':{'text':text},'elements':[{'ref':f'ui_{i}','text':str(i),'role':'button'} for i in range(100)]},
        'combat':{'weapon_info':{'ammunition_count':2}},'effects':[{'name':'Levitate','effects':[{'remaining_seconds':3}]}]}
    summary=compact(observation)
    assert len(json.dumps(summary))<len(text)/2
    assert summary['combat']['weapon_info']['ammunition_count']==2
    assert summary['effects'][0]['effects'][0]['remaining_seconds']==3
    s=SimpleNamespace(latest_observation=observation,command=lambda op:observation['ui'])
    complete=details(s,{'section':'ui'})
    assert present_response(complete)['data']['dialogue']['text']==text
    rows=query_ui(s,{'query':'99'})
    assert rows['total']==1 and rows['elements'][0]['ref']=='ui_99'
    assert 'text' not in rows['dialogue']
    with pytest.raises(BridgeError,match='stale_observation'):details(s,{'section':'ui','observation':3})


def test_evidence_is_observed_searchable_and_persistent(tmp_path):
    store=Knowledge(tmp_path/'agent.db')
    with pytest.raises(BridgeError,match='observed_evidence'):
        store.call({'action':'add','kind':'fact','text':'Unknown answer','evidence':'invented','quote':'secret'})
    ref=store.capture('document','Opened guide','Talk to the guide. He waits upstairs.')
    note=store.call({'action':'add','kind':'fact','text':'Guide upstairs','evidence':ref,'quote':'He waits upstairs.'})
    store.db.close();store=Knowledge(tmp_path/'agent.db')
    assert store.call({'action':'list'})['items'][0]['ref']==note['ref']
    assert store.call({'action':'evidence','ref':ref})['text']=='Talk to the guide. He waits upstairs.'
    assert store.call({'action':'evidence','query':'upstairs'})['evidence'][0]['ref']==ref


def test_finish_session_preserves_game_if_save_fails_and_finalizes_recording():
    calls=[]
    def call(op,*args):
        calls.append(op)
        if op=='save':raise BridgeError('save_unavailable')
    session=SimpleNamespace(call=call,stop_recording=lambda:calls.append('record_stop') or {'recording':False},close=lambda:calls.append('close'))
    result=finish_session(session,{})
    assert not result['closed'] and calls==['stop','save','record_stop']


def test_autosave_ring_overwrites_only_owned_slot_and_preserves_manual(tmp_path):
    auto=Autosave(tmp_path/'autosave.json');auto.configure({'enabled':True,'interval':1,'slots':2})
    slots=[{'ref':'manual','checkpoint_key':'manual-key','description':'My quest save'}];replaced=[]
    def command(op,args=None,**kwargs):
        if op=='saves':return {'saves':list(slots)}
        target=kwargs.get('_save_ref');replaced.append(target)
        if target: slots[:]=[s for s in slots if s['ref']!=target]
        slot={'ref':target or 'auto'+str(len(slots)), 'checkpoint_key':target or 'auto'+str(len(slots)), 'description':args['description']}
        slots.append(slot);return {'saves':list(slots)}
    session=SimpleNamespace(command=command,latest_observation={'state':'running','ui_mode':'Gameplay'},atlas=SimpleNamespace(checkpoint=lambda _:None))
    for time in (0,1,2,3):
        auto.observe({'simulation_seconds':time});auto.maybe_save(session)
    assert replaced==[None,None,'auto1'] and len(slots)==3
    assert slots[0]['ref']=='manual'
    before=auto.data['elapsed'];auto.observe({'simulation_seconds':5000},reset=True)
    assert auto.data['elapsed']==before


def enter(atlas,points):
    atlas.ingest({'state':'running','location':'Room','ui_mode':'Gameplay','simulation_seconds':100,'body':{'on_ground':True},
                 'trajectory':{'ref':'visit','start_heading_deg':0,'samples':[{'sequence':i+1,'forward_m':p[1],'sideways_m':p[0],'vertical_m':p[2],'heading_deg':0} for i,p in enumerate(points)]}},
                {'space':'Room','origin':[0,0,0]})


def test_route_failure_persists_expires_and_can_use_a_known_alternative(tmp_path,monkeypatch):
    now=[100.];monkeypatch.setattr('astra_bridge.atlas_routes.time.time',lambda:now[0])
    atlas=ExplorationAtlas(tmp_path/'atlas.json');enter(atlas,[[0,0,0]])
    origin=atlas.anchor_node('Origin')
    enter(atlas,[[0,0,0],[0,.5,0],[0,1,0],[0,1.5,0],[0,2,0],[0,2.5,0],[0,3,0]])
    alternate=atlas.anchor_node('Known landing')
    enter(atlas,[[0,0,0],[0,.5,0],[0,1,0],[0,1.5,0],[0,2,0],[0,2.5,0],[0,3,0],[0,3.5,0],[0,4,0]])
    target=atlas.anchor_node('Destination')
    atlas.current()['pose']=[0,0,0]
    atlas.record_outcome({'kind':'walk','ref':target['ref']},{'space':atlas.segment,'pose':[0,0,0]}, {'reason':'blocked','navigation':{'blocked_by':'actor'}})
    route=atlas.route_to(target['ref'])
    assert route and route['steps'][0]['ref']==alternate['ref']
    now[0]=10000
    assert len(atlas.route_outcomes(active=True))==1, 'thinking on pause does not age obstructions'
    atlas.simulation_seconds=109
    assert not atlas.route_outcomes(active=True)
    atlas.simulation_seconds=100
    atlas.db.close();atlas=ExplorationAtlas(tmp_path/'atlas.json')
    assert not atlas.route_outcomes(active=True), 'restart revalidates old obstructions'
    assert atlas.route_outcomes(), 'failure evidence remains persistent'


def test_native_guard_and_progress_algorithms():
    result=subprocess.run(['lua','tests/reliability.lua'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_sequence_damage_guard_interrupts_actual_long_motor_step():
    result=subprocess.run(['lua','tests/combat_adapter.lua','sequence_guard'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.parametrize('reason',['no_route_progress','repeated_positions','repeated_obstruction','target_obstructed','viewpoint_blocked'])
def test_navigation_failure_stops_compositions(reason):
    assert feedback('go',{'reason':reason},{},{})['status']=='blocked'
