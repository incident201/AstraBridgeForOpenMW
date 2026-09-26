from pathlib import Path
import subprocess
import pytest
from astra_bridge.protocol import validate,BridgeError,check_result
from astra_bridge.feedback import feedback
from astra_bridge.terrain_map import render_terrain


def test_local_survey():
    root=Path(__file__).resolve().parents[1]
    r=subprocess.run(['lua','tests/terrain.lua'],cwd=root,capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr

@pytest.mark.parametrize('args',[{'ref':'raw_world_id'},{'ref':'passage_x','seconds':99},{'ref':'passage_x','position':[1,2,3]},{'ref':'passage_x','run':1}])
def test_go_stays_bounded(args):
    with pytest.raises(BridgeError):validate('go',args)


def test_survey_projection_and_map(tmp_path):
    obs={'location':'<Room>','terrain':{'supported':True,'radius_m':6,'not_a_full_map':True,'rays':[
        {'bearing_deg':0,'clear_m':3,'height_change_m':-1,'status':'nav_boundary'}],
        'passages':[{'direction':'front','bearing_deg':0,'distance_m':2.25,'height_change_m':-.75,'status':'nav_boundary','ref':'passage_test'}]}}
    check_result(obs)
    out=tmp_path/'map.svg';render_terrain(obs,out)
    assert '&lt;Room&gt;' in out.read_text() and '3 m /' not in out.read_text()
    obs['terrain']['world_coordinates']=[1,2,3]
    with pytest.raises(BridgeError):check_result(obs)


def test_feedback_never_confuses_submission_with_success():
    assert feedback('choose',{'submitted':True},{},{})['status']=='submitted'
    result=feedback('choose',{'submitted':True},{},{'ui':{'elements':[{'role':'text','notice':'missing_mortar','text':'Need mortar'}]}})
    assert result['status']=='rejected' and result['events'][0]['kind']=='missing_mortar'
    expired=feedback('choose',{'submitted':True},{},{'messages':[{'text':'Need mortar','notice':'missing_mortar','frame':2}]})
    assert expired['status']=='rejected','a toast seen during the action remains evidence after it fades'
    assert feedback('go',{'reason':'step_limit'},{},{})['status']=='partial'
    assert feedback('go',{'reason':'blocked','navigation':{'blocked_by':'actor'}},{},{})['status']=='blocked'
    assert feedback('go',{'reason':'arrived'},{},{})['status']=='succeeded'
    near=feedback('walk',{'reason':'path_end_out_of_reach','motion':{'moved_m':12}},{},{})
    assert near['status']=='partial','a route that advanced but ended short must describe the partial progress'
    trade=feedback('choose',{'submitted':True,'changes':{'gold_change':-10}},{},{})
    assert trade['status']=='observed_change' and trade['events'][0]['amount']==-10
    stuck=feedback('act',{'reason':'duration','motion':{'moved_m':0}},{},{},{'move':1})
    assert stuck['status']=='blocked' and stuck['reason']=='no_observed_movement'
