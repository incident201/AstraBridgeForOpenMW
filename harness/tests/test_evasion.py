from pathlib import Path
import subprocess
import pytest
from astra_bridge.protocol import validate,BridgeError

def test_evasion_controller():
    r=subprocess.run(['lua','tests/evasion.lua'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr

@pytest.mark.parametrize('args',[{'direction':'forward'},{'direction':'back','meters':100},
    {'direction':'left','seconds':20},{'direction':'right','attack':True},{'direction':'back','run':1}])
def test_evasion_stays_bounded(args):
    with pytest.raises(BridgeError):validate('evade',args)

@pytest.mark.parametrize('movement',[{'direction':'up'},{'direction':'back','position':[0,0]},
    {'direction':'left','meters':100},{'direction':'forward','face_target':'yes'}])
def test_parallel_movement_validation(movement):
    with pytest.raises(BridgeError):validate('chain',{'actions':[{'op':'cast'}],'movement':movement})

def test_parallel_movement_accepts_self_cast_and_target_manoeuvre():
    validate('chain',{'actions':[{'op':'cast','spell':'Heal'}],'movement':{'direction':'forward','meters':3}})
    validate('evade',{'direction':'left','ref':'visible_x','actions':[{'op':'cast','item':'Ring'}]})

@pytest.mark.parametrize('value',[-1,101,True,float('nan')])
def test_chain_health_guard_is_a_bounded_percentage(value):
    with pytest.raises(BridgeError):validate('chain',{'actions':[{'op':'cast'}],'stop_health_pct':value})

def test_chain_wait_has_no_arbitrary_controls_or_unbounded_duration():
    validate('chain',{'actions':[{'op':'cast'},{'op':'wait','seconds':1}]})
    for step in [{'op':'wait','seconds':4},{'op':'wait','spell':'Hidden'},{'op':'wait','attack':True}]:
        with pytest.raises(BridgeError):validate('chain',{'actions':[step]})

def test_direct_movement_keeps_stock_cast_pulses_and_does_not_leak_between_actions():
    r=subprocess.run(['lua','tests/combat_adapter.lua','direct'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr

def test_movement_writer_does_not_touch_attack_or_look():
    script="""package.path='mod/?.lua;'..package.path
local m=require('scripts.astrabridge.movement_input')
local c={use=1,yawChange=.2,pitchChange=.3}
m.apply(c,{move=-1,strafe=.5,run=true},true,true,true)
assert(c.movement==-1 and c.sideMovement==.5 and c.run and c.jump and c.sneak)
assert(c.use==1 and c.yawChange==.2 and c.pitchChange==.3)
m.apply(c,nil,false,true,false)
assert(c.movement==0 and c.sideMovement==0 and not c.run and not c.jump and c.sneak)
assert(c.use==1,'movement must never erase the one-frame spell pulse')
"""
    r=subprocess.run(['lua','-'],input=script,cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr

def test_pursuit_range_controller():
    r=subprocess.run(['lua','tests/pursuit.lua'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr
    validate('chain',{'ref':'visible_x','pursue':True,'actions':[{'op':'strike'}]})
    for args in [{'pursue':1},{'pursue':True,'air':True},{'pursue':True,'movement':{'direction':'left'}}]:
        with pytest.raises(BridgeError):validate('chain',{'actions':[{'op':'strike'}],**args})
