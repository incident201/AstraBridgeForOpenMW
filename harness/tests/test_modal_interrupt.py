from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace

import pytest

from astra_bridge.autosave import Autosave
from astra_bridge.feedback import feedback
from astra_bridge.observations import present_response
from astra_bridge.workflows import sequence


def test_modal_interrupts_actual_player_adapter_in_every_action_phase():
    result=subprocess.run(['lua','tests/motor.lua','modal'],cwd=Path(__file__).parents[1],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.parametrize('mode',['modal','modal_direct'])
def test_modal_stops_combat_chain_and_both_movement_backends(mode):
    result=subprocess.run(['lua','tests/combat_adapter.lua',mode],cwd=Path(__file__).parents[1],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_native_interaction_modal_cannot_stall_confirmation_timer():
    result=subprocess.run(['lua','tests/combat_adapter.lua'],cwd=Path(__file__).parents[1],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_modal_feedback_is_interrupted_even_if_activation_already_happened():
    after={'ui_mode':'Gameplay','ui':{'modal':True,'text':'Please confirm',
           'elements':[{'role':'button','ref':'ui_ok','text':'OK','enabled':True}]}}
    for outcome in ('interrupted','activation_sent','taken'):
        action={'reason':'ui_input_required','outcome':outcome,'elapsed':.25}
        result=feedback('interact',action,{},after)
        assert result['status']=='interrupted' and result['reason']=='ui_input_required'
        assert any(e['kind']=='ui_input_required' and e['next_command']=='ui' for e in result['events'])
    summary=present_response({'action':action,'feedback':result,'observation':dict(after,observation=1,state='running')})
    assert summary['observation']['ui']['modal']
    assert summary['observation']['ui']['elements'][0]['ref']=='ui_ok'


def test_due_autosave_does_not_delay_reply_or_touch_a_modal(tmp_path):
    autosave=Autosave(tmp_path/'autosave.json');autosave.data['elapsed']=400
    session=SimpleNamespace(latest_observation={'state':'running','ui_mode':'Gameplay','ui':{'modal':True}},
                            command=lambda *args:(_ for _ in ()).throw(AssertionError('must not save during a modal')))
    assert autosave.maybe_save(session) is None


@pytest.mark.parametrize('interrupted',[True,False])
def test_sequence_stops_at_modal_in_action_or_final_observation(interrupted):
    current={'ui_mode':'Gameplay','ui':{'modal':False}}
    calls=[]
    def call(op,args):
        calls.append(op);current['ui']['modal']=True
        return {'action':{'reason':'ui_input_required' if interrupted else 'duration','elapsed':.2},
                'feedback':{'status':'interrupted' if interrupted else 'succeeded','reason':'ui_input_required' if interrupted else 'duration'},
                'observation':current}
    session=SimpleNamespace(observe=lambda **kwargs:current,call=call,
                            control=SimpleNamespace(cancelled=threading.Event(),progress=lambda _:None))
    result=sequence(session,{'actions':[{'op':'act','move':1,'seconds':30},{'op':'act','move':1,'seconds':30}]})
    assert calls==['act']
    assert result['feedback']['status']=='interrupted' and result['feedback']['reason']=='ui_input_required'
    assert result['observation']['ui']['modal']
