import pytest
from astra_bridge.feedback import feedback

@pytest.mark.parametrize('reason,status',[
    ('insufficient_magicka','rejected'),('no_ammunition','rejected'),
    ('out_of_reach','rejected'),('chain_time_limit','partial'),
    ('player_down','failed'),('action_not_started','failed'),('cannot_act','blocked'),
])
def test_combat_failures_are_not_reported_as_neutral_observations(reason,status):
    assert feedback('chain',{'reason':reason},{},{})['status']==status

def test_confirmed_pickup_uses_actual_lua_outcome():
    r=feedback('act',{'outcome':'taken'},{},{})
    assert r['status']=='succeeded' and r['events']==[{'kind':'item_taken'}]

def test_activation_duration_is_not_confirmation_that_a_door_opened():
    r=feedback('act',{'reason':'duration','outcome':'activation_sent'},{},{})
    assert r['status']=='submitted'

def test_death_during_an_ordinary_timed_action_is_failure():
    r=feedback('act',{'reason':'duration'},{'state':'running'},{'state':'ended','ui_mode':'MainMenu'})
    assert r['status']=='failed' and r['reason']=='player_down'
    r=feedback('act',{'reason':'duration'},{'state':'running'},{'state':'running','body':{'dead':True}})
    assert r['status']=='failed'

def test_failed_spell_animation_and_mana_spending_do_not_imply_success():
    after={'messages':[{'text':'Spell failed','frame':10,'notice':'spell_failed'}]}
    action={'reason':'completed','animation_complete':True,'resources':{'magicka_change':-45}}
    r=feedback('cast',action,{'messages':[]},after)
    assert r['status']=='failed' and r['reason']=='spell_failed'
    r=feedback('chain',{'reason':'completed','steps':[{'cast_outcome':'failed'}]},None,{})
    assert r['status']=='partial' and r['reason']=='spell_failed'
