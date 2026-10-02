from pathlib import Path
import subprocess
import pytest
from astra_bridge.exploration import ExplorationAtlas
from astra_bridge.protocol import check_result, BridgeError


def observation(samples, segment='public_1', heading=0):
    return {'state':'running','location':'<Cave>','ui_mode':'Gameplay','screenshot':'visible.png','body':{'on_ground':True},
            'trajectory':{'ref':segment,'sequence':samples[-1]['sequence'] if samples else 0,
                          'start_heading_deg':heading,'samples':samples,'sparse':False},
            'terrain':{'supported':True,'rays':[{'bearing_deg':90,'clear_m':4,'height_change_m':0,'status':'range_limit'}],
                       'passages':[{'bearing_deg':90,'distance_m':4,'height_change_m':0}]}}


def sample(sequence, forward=0, sideways=0, vertical=0, heading=0):
    return {'sequence':sequence,'forward_m':forward,'sideways_m':sideways,'vertical_m':vertical,'heading_deg':heading}


def test_lua_own_trajectory():
    r=subprocess.run(['lua','tests/trajectory.lua'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr


def test_visible_ground_candidates():
    r=subprocess.run(['lua','tests/ground.lua'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr


def test_map_uses_observed_samples_not_endpoint_shortcuts(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    obs=observation([sample(1),sample(2,forward=4),sample(3,forward=4,sideways=4)])
    check_result({'trajectory':obs['trajectory']});atlas.ingest(obs)
    assert [r['p'] for r in atlas.current()['points']]==[[0,0,0],[0,4,0],[4,4,0]]
    atlas.ingest(obs)
    assert len(atlas.current()['points'])==3,'transport re-reading is not movement'
    atlas.ingest(observation([sample(8,forward=10,sideways=10)]))
    assert atlas.current()['points'][-1]['gap'],'missing samples must break the drawn path'
    atlas.ingest(observation([sample(1)],segment='public_2'))
    assert len(atlas.current()['points'])==1 and len(atlas.data['segments'])==2


def test_origin_heading_and_visit_memory(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    first=observation([sample(1,heading=90)],heading=90);atlas.ingest(first)
    a=atlas.annotate(first);assert a['label']=='A1' and a['visits']==1
    atlas.annotate(first);assert a['visits']==1
    next_obs=observation([sample(2,forward=4,heading=90)],heading=90)
    atlas.ingest(next_obs);b=atlas.annotate(next_obs)
    assert b['p']==pytest.approx([4,0,0]) and b['label']=='A2'
    atlas.ingest(observation([sample(3,heading=90)],heading=90));atlas.annotate(first)
    assert a['visits']==2
    assert atlas.resolve(a['ref'])==a and atlas.resolve('A2')==b


def test_directions_and_vertical_separation(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    obs=observation([sample(1)]);atlas.ingest(obs);node=atlas.annotate(obs)
    assert len(atlas.untraversed(node))==1
    atlas.ingest(observation([sample(2,sideways=2)]))
    assert atlas.untraversed(node)==[]
    # Same XY on the floor above must not collapse into the old node.
    upper=observation([sample(3,vertical=3)]);atlas.ingest(upper);other=atlas.annotate(upper)
    assert other is not node and other['p'][2]==3


def test_markers_expire_and_map_escapes_labels(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    obs=observation([sample(1)]);atlas.ingest(obs);node=atlas.annotate(obs)
    node['motor_ref']='marker0';atlas.note_marker('marker0')
    for i in range(1,65):atlas.note_marker(f'marker{i}')
    assert not node.get('motor_ref')
    out=tmp_path/'map.svg';atlas.present(out)
    text=out.read_text();assert '&lt;Cave&gt;' in text and 'SECRET' not in text
    atlas.reset_runtime();assert atlas.resolve(node['ref']) is None
    obs['trajectory']['world_position']=[1,2,3]
    with pytest.raises(BridgeError):check_result({'trajectory':obs['trajectory']})

def test_desktop_map_keeps_geometry_without_the_agent_observation_panel(tmp_path):
    import xml.etree.ElementTree as ET
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    for i,(forward,sideways) in enumerate(((0,0),(4,0),(4,4))):
        obs=observation([sample(i+1,forward=forward,sideways=sideways)])
        atlas.ingest(obs);atlas.annotate(obs)
    desktop=atlas.present(tmp_path/'desktop.svg',map_only=True)
    normal=atlas.present(tmp_path/'agent.svg')
    assert desktop['nodes']==normal['nodes']
    assert 'map_markers' not in normal and 'map_bounds' not in normal
    assert {m['ref'] for m in desktop['map_markers']}=={n['ref'] for n in desktop['nodes']}
    bounds=desktop['map_bounds']
    for marker in desktop['map_markers']:
        assert bounds['left']<=marker['x']<=bounds['right']
        assert bounds['top']<=marker['y']<=bounds['bottom']
    assert bounds['left']<=.5<=bounds['right']
    root=ET.parse(tmp_path/'desktop.svg').getroot()
    assert root.attrib['viewBox']=='20 50 680 645'
    assert 'Visited observations' not in (tmp_path/'desktop.svg').read_text()
    assert 'Visited observations' in (tmp_path/'agent.svg').read_text()


def test_desktop_wide_area_keeps_distance_grid_bounded(tmp_path):
    import xml.etree.ElementTree as ET
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    obs=observation([sample(1)]);atlas.ingest(obs);atlas.annotate(obs)
    atlas.present(tmp_path/'wide.svg',radius=500,map_only=True)
    root=ET.parse(tmp_path/'wide.svg').getroot()
    rings=[e for e in root.iter('{http://www.w3.org/2000/svg}circle') if e.attrib.get('stroke')=='#253545']
    assert len(rings)<=7


def test_effect_explanations_do_not_expose_ids_or_random_rolls():
    e={'name':'Health effect','description':'Reduces health','health_effect':'damage','harmful':True}
    check_result({'effects':[e]})
    with pytest.raises(BridgeError):check_result({'effects':[{**e,'magnitudeThisFrame':12}]})
    with pytest.raises(BridgeError):check_result({'effects':[{**e,'id':'private_record'}]})


def test_save_checkpoint_restores_only_its_own_explored_branch(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    first=observation([sample(1)]);atlas.ingest(first);atlas.annotate(first)
    saved=observation([sample(2,forward=4)]);atlas.ingest(saved);atlas.annotate(saved)
    slot={'created':12.5,'description':'Repeated name','player_name':'Player','player_level':1}
    atlas.checkpoint(slot)
    # This later branch must not contaminate a reload of the earlier checkpoint.
    future=observation([sample(3,forward=12)]);atlas.ingest(future);atlas.annotate(future)
    atlas.checkpoint({**slot,'created':13})
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    atlas.restore(slot)
    loaded=observation([sample(1)],segment='after_load')
    atlas.ingest(loaded)
    assert atlas.current()['pose']==[0,4,0]
    assert len(atlas.current()['nodes'])==2
    assert atlas.resolve('A1')['restored'] and not atlas.resolve('A1').get('motor_ref')
    atlas.ingest(observation([sample(2,sideways=2)],segment='after_load'))
    assert atlas.current()['pose']==[2,4,0]
    atlas.checkpoint({**slot,'created':14})
    atlas.restore({**slot,'created':14})
    atlas.ingest(observation([sample(1)],segment='second_load'))
    assert atlas.current()['pose']==[2,4,0],'restored checkpoints can be saved and restored again'
    atlas.restore({**slot,'created':999})
    atlas.ingest(observation([sample(1)],segment='unknown_save'))
    assert atlas.current()['pose']==[0,0,0] and not atlas.current()['nodes']


def test_saved_map_does_not_attach_to_another_location(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    o=observation([sample(1,forward=8)]);atlas.ingest(o)
    slot={'created':1,'description':'A','player_name':'P','player_level':1};atlas.checkpoint(slot)
    atlas.restore(slot)
    changed=observation([sample(1)],segment='loaded');changed['location']='Different space'
    atlas.ingest(changed)
    assert atlas.current()['pose']==[0,0,0]
    from astra_bridge.protocol import validate
    with pytest.raises(BridgeError):validate('mark',{'_atlas_offset':[1,2,3]})


def test_jump_and_water_do_not_create_return_waypoints(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    for index,body in enumerate(({'on_ground':False},{'on_ground':True,'swimming':True},{'on_ground':True,'dead':True}),1):
        obs=observation([sample(index,vertical=2)]);obs['body']=body
        atlas.ingest(obs)
        assert atlas.annotate(obs) is None
    assert not atlas.current()['nodes']


def test_checkpoint_identity_survives_file_timestamp_settling(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    o=observation([sample(1,forward=4)]);atlas.ingest(o);atlas.annotate(o)
    slot={'checkpoint_key':'checkpoint_1234','created':12.995,'description':'Save','player_name':'P','player_level':1}
    atlas.checkpoint(slot)
    atlas.restore({**slot,'created':13.02})
    atlas.ingest(observation([sample(1)],segment='new_process'))
    assert atlas.current()['pose']==[0,4,0]
    atlas.restore({**slot,'created':100})
    atlas.ingest(observation([sample(1)],segment='overwritten_save'))
    assert atlas.current()['pose']==[0,0,0],'a later overwritten slot must not inherit the former path'


def test_copied_save_uses_recorded_play_time_instead_of_new_file_mtime(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    o=observation([sample(1,forward=4)]);atlas.ingest(o);atlas.annotate(o)
    slot={'checkpoint_key':'checkpoint_portable','created':1,'time_played_seconds':456.125,
          'description':'Save','player_name':'P','player_level':1}
    atlas.checkpoint(slot)
    atlas.restore({**slot,'created':99999})
    atlas.ingest(observation([sample(1)],segment='copied_save'))
    assert atlas.current()['pose']==[0,4,0]
    atlas.restore({**slot,'time_played_seconds':460.5})
    atlas.ingest(observation([sample(1)],segment='changed_content'))
    assert atlas.current()['pose']==[0,0,0]
    screenshots=tmp_path/'screenshots';screenshots.mkdir();(screenshots/'old-session.png').touch()
    assert atlas.portable_view('/different/machine/runtime/screenshots/old-session.png')==str(screenshots/'old-session.png')


def test_revisit_follows_connected_travel_around_corner_and_upstairs(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    first=observation([sample(1)]);atlas.ingest(first);node=atlas.annotate(first)
    # A loop around walls followed by stairs, ending directly above the start.
    rows=[sample(i+2,forward=min(i+1,4)) for i in range(4)]
    rows += [sample(i+6,forward=4,sideways=i+1,vertical=(i+1)*.5) for i in range(4)]
    rows += [sample(i+10,forward=3-i,sideways=4,vertical=2) for i in range(4)]
    rows += [sample(i+14,sideways=3-i,vertical=2) for i in range(4)]
    atlas.ingest(observation(rows))
    route=atlas.travelled_route(node)
    assert route[0]==[0,0,2] and route[-1]==[0,0,0]
    assert max(p[0] for p in route)==4 and max(p[1] for p in route)==4
    assert atlas.travelled_routes()[0][node['ref']][1]>16
    # Repeated labels/XY on another floor must never provide a shortcut.
    top=atlas.annotate(observation([]))
    assert top is not node
    view=atlas.present(tmp_path/'map.svg')
    public=next(n for n in view['nodes'] if n['ref']==node['ref'])
    assert public['can_revisit'] and public['distance_m']==0 and public['route_distance_m']>16
    # A missing transport sample disconnects the route rather than fabricating a line.
    atlas.ingest(observation([sample(100,forward=9,sideways=9,vertical=2)]))
    assert atlas.travelled_route(node) is None
    assert not next(n for n in atlas.present(tmp_path/'gap.svg')['nodes'] if n['ref']==node['ref'])['can_revisit']


def test_saved_revisit_uses_restored_trace_and_does_not_need_motor_handle(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    first=observation([sample(1)]);atlas.ingest(first);atlas.annotate(first)
    atlas.ingest(observation([sample(2,forward=1),sample(3,forward=2)]))
    slot={'created':1,'description':'S','player_name':'P','player_level':1}
    atlas.checkpoint(slot);atlas.restore(slot)
    atlas.ingest(observation([sample(1)],segment='restored'))
    node=atlas.resolve('A1')
    assert not node.get('motor_ref')
    assert atlas.travelled_route(node)==[[0,2,0],[0,1,0],[0,0,0]]
    from astra_bridge.protocol import validate
    with pytest.raises(BridgeError):
        validate('mark',{'_atlas_route':[[0,0,0]]})
    with pytest.raises(BridgeError):
        validate('go',{'ref':'waypoint_x','_atlas_route':[[0,0,0]]})


def test_slider_schema_and_observed_feedback():
    from astra_bridge.protocol import validate
    from astra_bridge.feedback import feedback
    validate('adjust',{'ref':'ui_current','position':7})
    check_result({'elements':[{'ref':'ui_current','role':'slider','slider_position':0,'slider_max':23}]})
    for value in (-1,1.5,True,1000001):
        with pytest.raises(BridgeError):validate('adjust',{'ref':'ui_current','position':value})
    before={'ui':{'elements':[{'role':'slider','slider_position':0}]}}
    after={'ui':{'elements':[{'role':'slider','slider_position':7}]}}
    r=feedback('adjust',{'submitted':True},before,after)
    assert r['status']=='observed_change' and {'kind':'slider_changed'} in r['events']
    assert feedback('adjust',{'submitted':True},before,before)['status']=='submitted'


def test_ballistic_motor_math_and_projection():
    r=subprocess.run(['lua','tests/ballistics.lua'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr
    check_result({'aim_assistance':'ballistic','estimated_flight_seconds':2.4,'aim_note':'shot_path_blocked'})
    with pytest.raises(BridgeError):check_result({'origin':{'x':1,'y':2,'z':3}})

def test_ballistic_adapter_rejects_a_blocked_weapon_path():
    r=subprocess.run(['lua','tests/combat_adapter.lua','blocked_shot'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr


def anchored(atlas, samples, visit='visit1', space='private_cell', origin=(100,200,3), heading=0):
    obs=observation(samples, segment=visit, heading=heading)
    atlas.ingest(obs, {'space':space, 'origin':list(origin)})
    return obs


def test_persistent_spaces_reentry_restart_and_heading(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    obs=anchored(atlas,[sample(1)])
    node=atlas.annotate(obs);ref=node['ref']
    anchored(atlas,[sample(i+2,forward=i+1) for i in range(4)])
    # Leave through one door, then return to the same position facing east.
    anchored(atlas,[sample(1)],'visit2','another_cell')
    anchored(atlas,[sample(1)],'visit3',origin=(100,204,3),heading=90)
    assert atlas.resolve(ref)['label']=='A1'
    assert atlas.travelled_route(atlas.resolve(ref))==[[0,4,0],[0,3,0],[0,2,0],[0,1,0],[0,0,0]]
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    anchored(atlas,[sample(1)],'after_restart',origin=(100,204,3),heading=270)
    assert atlas.resolve(ref) and atlas.travelled_route(atlas.resolve(ref))
    public=atlas.present(tmp_path/'map.svg')
    assert public['persistent'] and len(public['spaces'])==2
    assert 'private_cell' not in str(public) and 'anchor' not in str(public)
    assert (tmp_path/'atlas.sqlite3').exists()


def test_persistent_spaces_no_retention_limit_or_teleport_edge(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    anchored(atlas,[sample(1)])
    ref=atlas.segment
    for i in range(15):
        anchored(atlas,[sample(1)],f'visit{i+2}',f'cell{i}')
    assert len(atlas.catalog())==16
    anchored(atlas,[sample(1)],'back',origin=(120,200,3))
    assert atlas.segment==ref and atlas.current()['points'][-1]['gap']
    assert len(atlas.travelled_routes()[1])==1, 'teleport must not create a walkable edge'
    # Long visits and node histories must not silently discard earlier points.
    anchored(atlas,[sample(i+2,forward=(i+1)*.4) for i in range(5001)],'back',origin=(120,200,3))
    assert len(atlas.current()['points'])==5003


def test_persistent_new_game_separates_knowledge_and_load_selects_profile(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    obs=anchored(atlas,[sample(1)]);node=atlas.annotate(obs)
    slot={'created':10,'description':'Save','player_name':'P','player_level':1}
    atlas.checkpoint(slot)
    ref=node['ref'];profile=atlas.profile
    atlas.new_game()
    obs=anchored(atlas,[sample(1)],'newgame');atlas.annotate(obs)
    assert atlas.profile!=profile and atlas.resolve(ref) is None
    atlas.restore(slot)
    anchored(atlas,[sample(1)],'loaded')
    assert atlas.profile==profile and atlas.resolve(ref)


def test_persistent_save_load_keeps_learned_routes(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    obs=anchored(atlas,[sample(1)]);atlas.annotate(obs)
    slot={'created':10,'description':'Save','player_name':'P','player_level':1}
    atlas.checkpoint(slot)
    obs=anchored(atlas,[sample(2,forward=1),sample(3,forward=2),sample(4,forward=3)])
    node=atlas.annotate(obs)
    atlas.restore(slot)
    anchored(atlas,[sample(1)],'loaded')
    assert atlas.resolve(node['ref']) and atlas.travelled_route(node)


def test_legacy_checkpoint_migrates_only_when_position_known(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    old=observation([sample(1),sample(2,forward=1),sample(3,forward=2)])
    atlas.ingest(old);atlas.annotate(old)
    slot={'created':1,'description':'Old','player_name':'P','player_level':1}
    atlas.checkpoint(slot);atlas.restore(slot)
    anchored(atlas,[sample(1)],'new',origin=(500,600,0))
    assert atlas.current()['pose']==[0,2,0]
    anchored(atlas,[sample(1)],'other',space='other')
    anchored(atlas,[sample(1)],'returned',origin=(500,600,0))
    assert atlas.current()['pose']==[0,2,0]
    assert len(atlas.current()['nodes'])==1


def test_unknown_save_of_other_player_isolated(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    o=anchored(atlas,[sample(1)]);node=atlas.annotate(o)
    atlas.checkpoint({'created':1,'description':'S','player_name':'A','player_level':1})
    atlas.restore({'created':2,'description':'S2','player_name':'B','player_level':1})
    anchored(atlas,[sample(1)],'other_player')
    assert atlas.resolve(node['ref']) is None


def test_disconnected_known_point_requires_native_path_not_invented_trail(tmp_path):
    atlas=ExplorationAtlas(tmp_path/'atlas.json')
    o=anchored(atlas,[sample(1)]);node=atlas.annotate(o)
    anchored(atlas,[sample(1)],'other_door',origin=(110,200,3))
    assert atlas.travelled_route(node) is None
    row=atlas.present(tmp_path/'map.svg')['nodes'][0]
    assert row['can_revisit'] and row['revisit_source']=='native_path_required'
    archived=atlas.present(tmp_path/'archive.svg',archived=True)['nodes'][0]
    assert not archived['can_revisit'] and archived['revisit_source']=='different_space'


def test_private_atlas_metadata_rejected_at_public_boundary():
    with pytest.raises(BridgeError): check_result({'_atlas_frame':{'space':'private', 'origin':[1,2,3]}})
