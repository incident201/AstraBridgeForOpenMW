import subprocess
import threading
from pathlib import Path

import pytest

from astra_bridge.protocol import BridgeError, check_result, validate
from astra_bridge.session import Session
from astra_bridge.feedback import feedback


def test_player_status_is_one_read_without_screenshot_or_inventory_ref_reset():
    session=object.__new__(Session)
    session.lock=threading.RLock()
    session.latest_observation=None
    calls=[]
    def command(op,args):
        calls.append((op,args))
        return {'player_name':'Test','carried_weight':12,'capacity':200,'effects':[]}
    session.command=command
    assert session.call('status',{'player':True})['capacity']==200
    assert calls==[('inspect',{'view':'character'})]


@pytest.mark.parametrize('args',[{}, {'vertical_m':float('inf')}, {'vertical_m':float('nan')},
                                {'vertical_m':10,'seconds':0},{'vertical_m':20,'forward_m':True}])
def test_invalid_flight_is_rejected(args):
    with pytest.raises(BridgeError):validate('fly',args)


def test_flight_expiry_is_interruption_and_character_fields_are_projected():
    validate('fly',{'vertical_m':8,'seconds':12})
    validate('inspect',{'view':'character'})
    check_result({'effects':[{'name':'Poison','temporary':True,'effects':[{'name':'Poison',
        'harmful':True,'duration':20,'remaining_seconds':12,'permanent':False}]}],
        'body':{'levitation':False,'water_walking':True},
        'stats':{'attribute_details':[{'name':'Strength','base':40,'value':30,'damage':10}]}})
    assert feedback('fly',{'reason':'levitation_ended'},None,{})['status']=='interrupted'


def test_flight_motor():
    r=subprocess.run(['lua','tests/flight.lua'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr

def test_camera_policy():
    r=subprocess.run(['lua','tests/camera_policy.lua'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr
