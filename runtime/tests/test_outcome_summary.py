import copy
import math
import threading
from types import SimpleNamespace

import pytest

from astra_bridge.feedback import feedback
from astra_bridge.observations import present_response
from astra_bridge.outcomes import MotionSpan, horizontal_displacement, summarize
from astra_bridge.protocol import BridgeError
from astra_bridge.selectors import check_expectation
from astra_bridge.workflows import navigate, sequence, validate_sequence


def motor(op='act',inputs=None,forward=0,side=0,vertical=0,seconds=3,**fields):
    a={'reason':'duration','elapsed':seconds,'motion':{'forward_m':forward,'sideways_m':side,
        'vertical_m':vertical,'moved_m':math.sqrt(forward**2+side**2+vertical**2),'location_changed':False},**fields}
    return summarize({'action':a,'feedback':feedback(op,a,{}, {},inputs or {}),'observation':{}},op)


@pytest.mark.parametrize('vertical',[.46,-.46,10])
def test_vertical_motion_is_not_horizontal_progress(vertical):
    r=motor(inputs={'move':1,'seconds':3},vertical=vertical)
    assert r['feedback']['status']=='blocked' and r['feedback']['reason']=='no_horizontal_progress'
    assert r['summary']['horizontal_displacement_m']==0
    assert r['summary']['warnings']==['no_horizontal_progress']
    assert r['summary']['encountered_blockers']==[], 'zero progress does not identify an NPC or a wall'


def test_short_inputs_stationary_jumps_and_real_horizontal_motion_are_not_blocked():
    assert motor(inputs={'move':1,'seconds':.02},vertical=-.46,seconds=2)['feedback']['status']=='succeeded'
    assert motor(inputs={'trigger':'Jump'},vertical=.46,aerial={'took_off':True})['feedback']['status']=='succeeded'
    assert motor(inputs={'strafe':1},side=1)['summary']['horizontal_displacement_m']==1
    assert motor(inputs={'move':1},forward=.03,side=.04)['feedback']['status']=='succeeded'
    for op in ['jump','air_move']:
        assert motor(op,{'direction':'none'},vertical=.46,reason='landed')['feedback']['status']=='succeeded'
        assert motor(op,{'direction':'forward'},vertical=.46,reason='landed')['feedback']['status']=='blocked'
    r=motor(inputs={'move':1},outcome='taken')
    assert r['feedback']['status']=='partial' and r['feedback']['events']==[{'kind':'item_taken'}]
    assert r['summary']['status']==r['feedback']['status']


def test_absent_or_discontinuous_motion_is_unknown_not_zero():
    assert horizontal_displacement({}) is None
    assert horizontal_displacement({'motion':{'moved_m':.46}}) is None
    assert horizontal_displacement({'motion':{'forward_m':0,'sideways_m':0,'location_changed':True}}) is None
    a={'reason':'duration','motion':{'forward_m':0,'sideways_m':0,'location_changed':True}}
    assert feedback('act',a,{},{},{'move':1})['status']=='succeeded'


class World:
    def __init__(self):
        self.graph={'ref':'space_test','pose':[0.,0.,0.],'anchor':[700,800,900],'location':'Room'}
        self.atlas=SimpleNamespace(profile='profile',visit='visit',clock_epoch='clock',current=lambda:self.graph)
        self.control=SimpleNamespace(cancelled=threading.Event(),progress=lambda _:None)
        self.calls=[]
    def observe(self,**kwargs):
        return {'state':'running','ui_mode':'Gameplay','location':'Room','orientation':{'heading_deg':0},
                'stats':{'health':{'current':35,'maximum':35}}}


def test_jump_then_blocked_move_stops_sequence_before_consuming_item():
    s=World()
    def call(op,args):
        s.calls.append(op)
        if op!='act':pytest.fail('a dependent step was executed after blocked movement')
        jump=args.get('trigger')=='Jump';vertical=.46 if jump else -.46
        s.graph['pose'][2]+=vertical
        r=motor(op,args,vertical=vertical,seconds=args['seconds'],**({'aerial':{'took_off':True}} if jump else {}))
        r['observation']=s.observe();return r
    s.call=call
    r=sequence(s,{'actions':[{'op':'act','trigger':'Jump','seconds':.1},
        {'op':'act','move':1,'seconds':3},{'op':'use_item','ref':'item_potion'}]})
    assert s.calls==['act','act']
    assert r['action']['completed_actions']==1 and r['action']['stopped_step']==2
    assert r['feedback']['status']=='blocked' and r['summary']['status']=='blocked'
    assert r['summary']['stalled_attempts']==1 and r['summary']['horizontal_displacement_m']==0
    assert r['action']['steps'][1]['feedback']['reason']=='no_horizontal_progress'
    assert r['summary']['warnings']==['no_horizontal_progress']


def test_sequence_endpoint_metric_is_not_the_sum_of_steps_and_return_is_not_failure():
    s=World()
    def call(op,args):
        delta=2*args['move'];s.graph['pose'][0]+=delta
        r=motor(op,args,forward=delta);r['observation']=s.observe();return r
    s.call=call
    r=sequence(s,{'actions':[{'op':'act','move':1,'seconds':3},{'op':'act','move':-1,'seconds':3}]})
    assert r['summary']['horizontal_displacement_m']==0 and r['summary']['warnings']==[]
    assert r['feedback']['status']=='succeeded'
    span=MotionSpan(s);s.graph['ref']='other';span.sample(s);s.graph['ref']='space_test';span.sample(s)
    assert span.distance() is None
    span=MotionSpan(s);s.atlas.visit='new_stroke';span.sample(s)
    assert span.distance() is None, 'a teleport/load must not be measured in a supposedly unchanged frame'


@pytest.mark.parametrize('value',[-1,True,'1',float('inf'),float('nan')])
def test_minimum_displacement_expectation_requires_a_finite_nonnegative_number(value):
    with pytest.raises(BridgeError):validate_sequence({'actions':[{'op':'act','move':1,
        'expect':{'min_horizontal_displacement_m':value}}]})


def test_minimum_displacement_failure_is_recorded_and_does_not_continue():
    s=World()
    def call(op,args):
        s.calls.append(op);r=motor(op,args,forward=.2);r['observation']=s.observe();return r
    s.call=call
    r=sequence(s,{'actions':[{'op':'act','move':1,'seconds':3,'expect':{'min_horizontal_displacement_m':.5}},
        {'op':'use_item','ref':'item_potion'}]})
    assert s.calls==['act'] and r['action']['reason']=='expectation_failed'
    assert r['feedback']['status']=='failed' and r['action']['steps'][0]['checks'][0]['actual']==.2
    check=check_expectation(s,{'min_horizontal_displacement_m':0},{},{},{'motion':{'location_changed':True}})[0]
    assert check['actual'] is None and not check['met'] and check['reason']=='movement_not_comparable'


def navigation_world():
    s=World();node={'ref':'node_test','p':[10,0,0]}
    s.atlas.segment='space_test'
    s.atlas.route_to=lambda _: {'destination':'node_test','steps':[{'kind':'walk','ref':'node_test'}]}
    s.atlas.find_node=lambda _: (s.graph,node)
    s.atlas.travelled_route=lambda _:None
    s.atlas.record_outcome=lambda *args:None
    s.command=lambda *args,**kwargs:{'ref':'waypoint_current'}
    def call(op,args):
        if op=='revisit':return navigate(s,args)
        s.calls.append((op,args));index=len(s.calls)
        a={'reason':'no_route_progress' if index<3 else 'step_limit','elapsed':3 if index<3 else 14,
           'motion':{'forward_m':0,'sideways_m':0},'navigation':{'blocked_by':'actor' if index<3 else None}}
        return summarize({'action':a,'feedback':feedback(op,a,{},{},args),'observation':s.observe()},op)
    s.call=call
    return s


def test_revisit_retains_blockers_before_time_limit_and_counts_attempts_once():
    s=navigation_world();r=navigate(s,{'ref':'node_test','seconds':20,'run':True})
    summary=r['summary']
    assert r['action']['reason']=='step_limit' and summary['termination']=='time_limit'
    assert summary['destination_reached'] is False and summary['encountered_blockers']==['actor']
    assert summary['stalled_attempts']==2 and summary['elapsed']==20
    assert [a['reason'] for a in r['action']['attempts']]==['no_route_progress','no_route_progress','step_limit']
    assert [c[1]['seconds'] for c in s.calls]==[20,17,14]
    assert r['action']['steps'][0]['feedback']['reason']=='no_route_progress'
    assert '700' not in str(summary) and 'pose' not in str(summary)
    nested=sequence(navigation_world(),{'actions':[{'op':'revisit','ref':'node_test','seconds':20},{'op':'act'}]})
    assert nested['summary']['stalled_attempts']==2 and nested['summary']['encountered_blockers']==['actor']
    assert nested['action']['stopped_step']==1 and nested['feedback']['status']=='partial'


def test_revisit_later_route_error_keeps_previous_diagnostics():
    s=navigation_world();plan=s.atlas.route_to;calls=[]
    def route(ref):
        calls.append(ref);return plan(ref) if len(calls)<3 else None
    s.atlas.route_to=route
    r=navigate(s,{'ref':'node_test','seconds':20})
    assert r['action']['reason']=='recorded_route_unavailable'
    assert r['summary']['stalled_attempts']==1 and r['summary']['encountered_blockers']==['actor']
    assert len(r['action']['steps'])==1 and r['action']['attempts'][1]['result_available'] is False


def test_summary_survives_compaction_and_does_not_infer_the_blocker():
    first={'reason':'no_route_progress','navigation':{'blocked_by':'actor'}}
    r=summarize({'action':{'reason':'step_limit','steps':[first]+[{'reason':'arrived'}]*10},
                 'feedback':{'status':'interrupted','reason':'step_limit'}},'revisit',None)
    compact=present_response(r)
    assert len(compact['action']['steps'])==8 and compact['action']['steps_has_more']
    assert compact['summary']['stalled_attempts']==1 and compact['summary']['encountered_blockers']==['actor']
    assert compact['summary']==r['summary']
    assert summarize({'action':{'reason':'no_route_progress'}},'go')['summary']['encountered_blockers']==[]


def test_exterior_label_change_is_not_a_coordinate_discontinuity():
    a={'motion':{'forward_m':2,'sideways_m':0,'location_changed':False},'changes':{'location_changed':True}}
    assert horizontal_displacement(a)==2
    a['outcome']='location_changed'
    assert horizontal_displacement(a) is None



def test_uncertain_motor_result_is_not_promoted_to_a_completed_sequence_receipt():
    s=World();s.uncertain=False
    def call(op,args):
        s.uncertain=True;raise BridgeError('game_operation_timeout')
    s.call=call
    with pytest.raises(BridgeError,match='game_operation_timeout'):
        sequence(s,{'actions':[{'op':'act','move':1,'seconds':3}]})
    assert s.batch_depth==0 and s.sequence_guard is None


def test_receipt_summary_can_be_read_without_observation_or_step_loss():
    from astra_bridge.information import receipt_details
    from astra_bridge.cli import build_parser
    summary={'status':'partial','termination':'time_limit','encountered_blockers':['actor'],'stalled_attempts':2}
    receipt={'request_id':'request','status':'completed','response':{'summary':summary}}
    assert receipt_details(receipt,{'section':'summary'})['response']=={'section':'summary','data':summary}
    args=vars(build_parser().parse_args(['action-result','request','--section','summary']))
    assert args['section']=='summary'
