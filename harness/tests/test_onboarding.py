"""Regressions exposed by a fresh player's first session."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from astra_bridge.dependencies import offline_runtime
from astra_bridge.information import details, receipt_details
from astra_bridge.observations import present_response
from astra_bridge.protocol import BridgeError, validate
from astra_bridge.control import Control
from astra_bridge.feedback import feedback


@pytest.fixture
def wheel_fixture(tmp_path):
    # Source checkouts contain no wheels. Release packaging checks real wheels.
    (tmp_path/'requirements.txt').write_text((Path(__file__).parents[1]/'requirements.txt').read_text())
    directory=tmp_path/'wheelhouse';directory.mkdir()
    for name in ['mss-10.2.0-py3-none-any.whl', 'imageio_ffmpeg-0.6.0-py3-none-manylinux2014_x86_64.whl']:
        (directory/name).touch()
    for minor in (11,12,13,14):
        (directory/f'pillow-12.3.0-cp3{minor}-cp3{minor}-manylinux_2_28_x86_64.whl').touch()
    return tmp_path


@pytest.mark.parametrize('minor',[11,12,13,14])
def test_offline_wheel_selection_for_supported_python(minor,wheel_fixture):
    r=offline_runtime(wheel_fixture,version=(3,minor),implementation='cpython',architecture='x86_64',threaded=False)
    assert r['available'],r
    assert len(r['wheels'])==3 and 'Pillow' in r['wheels']


def test_unsupported_offline_abi_is_explicit(wheel_fixture):
    r=offline_runtime(wheel_fixture,version=(3,14),implementation='cpython',architecture='x86_64',threaded=True)
    assert not r['available'] and r['missing']==['Pillow==12.3.0']


def test_scan_is_bounded_with_exact_headings_and_all_data_retrievable():
    views=[]
    for i,heading in enumerate([20,110,200,290]):
        o={'observation':123+i,'state':'running','ui_mode':'Gameplay','orientation':{'heading_deg':heading,'pitch_deg':0},
           'scene':{'objects':[{'ref':f'v{i}_{n}','kind':'door' if n==50 else 'item','name':'Предмет '+str(n)} for n in range(100)]},
           'messages':[{'text':'Текст '+str(n),'frame':n} for n in range(20)]}
        views.append({'observation':o})
    raw={'views':views,'final':views[-1]['observation']};saved=copy.deepcopy(raw)
    small=present_response(raw)
    assert len(json.dumps(small,ensure_ascii=False))<12000
    assert [v['heading_deg'] for v in small['views']]==[20,110,200,290]
    assert 'v0_50' in [o['ref'] for o in small['views'][0]['landmarks']]
    receipt={'request_id':'scan1','response':raw}
    detail=receipt_details(receipt,{'view':2,'section':'scene','query':'Предмет 99'})
    assert detail['historical'] and detail['response']['data']['objects'][0]['ref']=='v2_99'
    assert raw==saved
    with pytest.raises(BridgeError,match='invalid_view'):receipt_details(receipt,{'view':4})


def test_action_target_and_locked_door_remain_visible_in_summary():
    o={'scene':{'objects':[{'ref':str(i),'kind':'door','description':'Locked 50'} for i in range(30)]}}
    r=present_response(o|{'observation':1,'state':'running'},target_ref='29')
    assert r['scene']['objects'][0]['ref']=='29'
    assert r['scene']['objects'][0]['description']=='Locked 50'


def test_details_bad_section_points_to_inventory_interface():
    with pytest.raises(BridgeError) as e:details(SimpleNamespace(latest_observation={'observation':1}),{'section':'inventory'})
    assert e.value.response()['next_command']=='inspect inventory'
    assert 'scene' in e.value.details['supported_sections']


def test_disabled_controls_error_has_receipt_and_recovery(tmp_path):
    def call(op,args):raise BridgeError('action_unavailable')
    s=SimpleNamespace(inbox=tmp_path/'inbox.json',latest_observation={'observation':1,'ui_mode':'Gameplay','body':{'controls_enabled':False}},uncertain=False,call=call)
    c=Control(s)
    with pytest.raises(BridgeError) as e:c.execute('approach',{'ref':'visible_1'})
    result=e.value.response()
    assert result['reason']=='player_controls_disabled'
    assert result['next_command']=='wait-until controls --seconds 10'
    assert c.execute('action_result',{'ref':result['request_id']})['status']=='rejected'
    validate('wait_until',{'condition':'controls','control':'looking','seconds':15})
    with pytest.raises(BridgeError):validate('wait_until',{'condition':'animation','control':'looking'})


def test_interaction_requires_observed_outcome():
    unconfirmed=feedback('interact',{'outcome':'activation_sent','reason':'completed'}, {}, {'messages':[{'text':'Take the papers','frame':1}]})
    assert unconfirmed['status']!='succeeded'
    assert any(e['kind']=='activation_unconfirmed' for e in unconfirmed['events'])
    opened=feedback('interact',{'outcome':'document_opened','reason':'completed'}, {}, {})
    assert opened['status']=='succeeded'


@pytest.mark.parametrize('op,args,body,reason,next_command',[
    ('look',{'heading_deg':30},{'controls_enabled':True,'looking_enabled':False},'player_looking_disabled','wait-until controls --control looking --seconds 10'),
    ('act',{'trigger':'Jump'},{'controls_enabled':True,'jumping_enabled':False},'player_jumping_disabled','wait-until controls --control jumping --seconds 10'),
    ('interact',{'ref':'visible_1'},{'controls_enabled':True},None,'status --player'),
])
def test_unavailable_recovery_uses_the_actual_disabled_control(tmp_path,op,args,body,reason,next_command):
    def call(op,args):raise BridgeError('action_unavailable')
    s=SimpleNamespace(inbox=tmp_path/'inbox.json',latest_observation={'observation':1,'ui_mode':'Gameplay','body':body},uncertain=False,call=call)
    with pytest.raises(BridgeError) as e:Control(s).execute(op,args)
    assert e.value.details.get('reason')==reason
    assert e.value.details['next_command']==next_command


def test_cli_help_and_errors_are_self_describing():
    import subprocess,sys
    root=Path(__file__).parents[1]
    help_result=subprocess.run([sys.executable,'-m','astra_bridge.cli','details','--help'],cwd=root,capture_output=True,text=True)
    assert help_result.returncode==0 and 'exploration' in help_result.stdout and 'inspect' in help_result.stdout
    error=subprocess.run([sys.executable,'-m','astra_bridge.cli','invented-command'],cwd=root,capture_output=True,text=True)
    assert error.returncode==2 and len(error.stderr)<300 and '--help' in error.stderr
