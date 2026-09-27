from astra_bridge.memory import SpatialMemory
from astra_bridge.protocol import check_result, BridgeError, validate
import pytest


def test_graph_persists_evidence_and_does_not_assume_command_means_arrival(tmp_path):
    memory = SpatialMemory(tmp_path/'memory.json')
    obs = {'state':'running','observation':3,'screenshot':'observed.png','location':'Room',
           'orientation':{'heading_deg':90},'scene':{'objects':[{'name':'Door'}]}}
    first = memory.remember('Landing','Door on the left',['left door'],'observed',obs)
    memory.record_step('move_local',{'forward_m':1},{'motion':{'moved_m':.6},'reason':'blocked'},obs)
    assert memory.route()['anchor']['status'] == 'last_seen_not_current'
    second = memory.remember('Hall','Return path',['stairs'],'observed',obs)
    memory.connect(first['ref'],second['ref'],'through doorway')
    reloaded = SpatialMemory(tmp_path/'memory.json')
    assert len(reloaded.recall()['places']) == 2
    assert reloaded.recall()['links'][0]['evidence'][0]['reason'] == 'blocked'
    reloaded.branch('load')
    assert not reloaded.recall()['places']
    assert len(reloaded.recall(archived=True)['places']) == 2


def test_scene_projection_accepts_screen_coordinates_but_rejects_world_state():
    scene={'scene':{'objects':[{'ref':'visible_1','name':'Door','rect':[10,20,30,40],
                              'aim_point':[20,30],'distance_m':2.5,'actions':['focus']}],
                    'sampling_limited':False}}
    check_result(scene)
    scene['scene']['objects'][0]['world_position']=[10,20,30]
    with pytest.raises(BridgeError):check_result(scene)


@pytest.mark.parametrize('args',[{'forward_m':float('inf')},{'forward_m':float('nan')},{'position':[0,0,0]}])
def test_local_movement_remains_bounded(args):
    with pytest.raises(BridgeError):validate('move_local',args)


def test_travel_invalidates_anchor_without_a_movement_command(tmp_path):
    from astra_bridge.session import observation_changes
    memory=SpatialMemory(tmp_path/'memory.json')
    before={'state':'running','location':'Seyda Neen','ui_mode':'Travel','stats':{'gold':67}}
    memory.remember('Port','',[],'observed',before)
    after={'state':'running','location':'Balmora','ui_mode':'Gameplay','stats':{'gold':52}}
    changes=observation_changes(before,after)
    assert changes['gold_change']==-15 and changes['location_changed']
    memory.observe_location(after)
    assert memory.route()['anchor']['status']=='last_seen_not_current'
    memory.record_step('choose',{'ref':'ui_test'},{'changes':changes},after)
    assert memory.route()['steps'][-1]['motion']=={'location_changed':True}
