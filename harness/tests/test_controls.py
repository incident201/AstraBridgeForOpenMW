import threading
from types import SimpleNamespace

import pytest

from astra_bridge import selectors, services, workflows
from astra_bridge.doors import observed_anchor, match_door
from astra_bridge.protocol import BridgeError, validate, check_result


@pytest.mark.parametrize('label',['Отдых','Rest','Repos','休息','arbitrary translated caption'])
def test_select_controls_without_interpreting_localized_caption(label):
    revision=[0]
    def ui(op):
        revision[0]+=1
        return {'elements':[{'ref':f'ui_{revision[0]}','control':'rest_confirm','text':label,'enabled':True}]}
    session=SimpleNamespace(command=ui)
    step={'op':'choose','select':{'control':'rest_confirm'},'bind':'button'}
    selectors.validate_step(step,set())
    bindings={}
    assert selectors.resolve_step(session,step,bindings)[0]['ref']=='ui_1'
    assert selectors.resolve_step(session,step,bindings)[0]['ref']=='ui_2'
    assert bindings['button']=='ui_2'


def test_ambiguous_or_disabled_selector_never_submits():
    row={'name':'Door','kind':'door','distance_m':2,'ref':'visible_1'}
    session=SimpleNamespace(observe=lambda **kw:{'scene':{'objects':[row,dict(row,ref='visible_2')]}})
    with pytest.raises(BridgeError,match='ambiguous'):
        selectors.resolve_step(session,{'op':'interact','select':{'name':'Door','nearest':True}}, {})
    session.command=lambda op:{'elements':[{'control':'rest_confirm','enabled':False}]}
    with pytest.raises(BridgeError,match='unavailable'):
        selectors.resolve_step(session,{'op':'choose','select':{'control':'rest_confirm'}},{})


def test_postcondition_failure_stops_before_consumable():
    calls=[]
    observation={'ui_mode':'Dialogue','location':'Room','simulation_seconds':0,'stats':{'gold':20}}
    def call(op,args):
        calls.append(op)
        return {'action':{'submitted':True},'observation':observation}
    session=SimpleNamespace(observe=lambda **kw:observation,call=call,
        control=SimpleNamespace(cancelled=threading.Event(),progress=lambda _:None))
    r=workflows.sequence(session,{'actions':[
        {'op':'choose','ref':'ui_old','expect':{'ui_mode':'Barter'}},
        {'op':'use_item','ref':'item_consumable'}]})
    assert calls==['choose']
    assert r['action']['reason']=='expectation_failed'
    assert not r['action']['steps'][0]['checks'][0]['met']


def test_sequence_validates_all_selectors_and_bindings_before_mutation():
    with pytest.raises(BridgeError,match='unknown_sequence_binding'):
        workflows.validate_sequence({'actions':[{'op':'focus','ref':'$future'}]})
    with pytest.raises(BridgeError,match='invalid_selector_source'):
        workflows.validate_sequence({'actions':[{'op':'choose','select':{'source':'scene','kind':'actor'}}]})
    workflows.validate_sequence({'actions':[{'op':'focus','select':{'kind':'actor','nearest':True},'bind':'npc'},
        {'op':'interact','ref':'$npc','expect':{'ui_mode':'Dialogue'}}]})


def test_door_selection_uses_center_geometry_and_floor():
    door={'name':'Same name','description':'Same destination','anchor':[0,3,1]}
    row={'kind':'door','name':door['name'],'description':door['description'],'horizontal_distance_m':3,
         'height_change_m':1,'center_bearing_deg':0,'bearing_deg':30,'ref':'lower'}
    assert observed_anchor(row,[0,0,0],0)==[0,3,1], 'aim point must not distort wide-door center'
    assert match_door([dict(row,name='Localized new name')],door,[0,0,0],0)[0] is not None
    upper=dict(row,height_change_m=4,ref='upper')
    assert match_door([upper,row],door,[0,0,0],0)[0]['ref']=='lower'
    assert match_door([upper],door,[0,0,0],0)[0] is None
    assert match_door([row,dict(row,ref='duplicate')],door,[0,0,0],0)[1]=='door_ambiguous'
    assert match_door([row,upper],{'name':door['name'],'description':door['description']},[0,0,0],0)[0] is None


class Shop:
    def __init__(self,caption='Offer',price=10,accept=True):
        self.caption=caption;self.price=price;self.accept=accept;self.mode='shop'
        self.gold=100;self.owned=2;self.quantity=0;self.calls=[];self.revision=0
        self.control=SimpleNamespace(cancelled=threading.Event())
    def observe(self,**kwargs):
        return {'stats':{'gold':self.gold},'ui_mode':'Barter','location':'Room'}
    def command(self,op,args=None):
        if op=='inspect':return {'items':[{'name':'Localized item','count':self.owned}]}
        self.revision+=1
        def row(control,**kwargs):
            return {'ref':f'ui_{self.revision}_{control}','control':control,'text':self.caption,'enabled':True,**kwargs}
        self.rows=[row('quantity_slider',slider_max=4),row('quantity_confirm')] if self.mode=='quantity' else [
            row('trade_offer'),row('trade_cancel'),row('trade_balance',enabled=False,value=str(-self.price)),
            row('merchant_item',text='Localized item',role='item',panel='merchant',count=5)]
        return {'elements':self.rows}
    def call(self,op,args):
        assert args['ref'].startswith(f'ui_{self.revision}_'), 'must reacquire after each UI mutation'
        control=args['ref'].split('_',2)[2];self.calls.append(control)
        if control=='merchant_item':self.mode='quantity'
        elif control=='quantity_slider':self.quantity=args['position']+1
        elif control=='quantity_confirm':self.mode='shop'
        elif control=='trade_offer' and self.accept:self.owned+=self.quantity;self.gold-=self.price
        return {'action':{'submitted':True}}


@pytest.mark.parametrize('caption',['Предложить','Offer','Proposer','取引'])
def test_buy_quantity_and_price_are_structured_not_parsed_from_text(caption):
    s=Shop(caption)
    args={'name':'Localized item','quantity':3,'max_total':20}
    r=services.buy(s,args,services.Service(s,args))
    assert r['reason']=='purchase_complete' and r['gold_spent']==10 and r['quantity_received']==3
    assert s.calls==['merchant_item','quantity_slider','quantity_confirm','trade_offer']


def test_price_ceiling_cancels_cart_without_submitting_offer():
    s=Shop(price=30);args={'name':'Localized item','quantity':2,'max_total':20}
    r=services.buy(s,args,services.Service(s,args))
    assert r['reason']=='price_limit' and not r['submitted']
    assert s.calls[-1]=='trade_cancel' and 'trade_offer' not in s.calls
    assert s.gold==100 and s.owned==2


def test_rejected_purchase_is_not_automatically_repeated():
    s=Shop(accept=False);args={'name':'Localized item','quantity':2,'max_total':20}
    r=services.buy(s,args,services.Service(s,args))
    assert r['reason']=='trade_unconfirmed' and s.calls.count('trade_offer')==1


def test_cancel_prevents_ui_mutation():
    s=Shop();s.control.cancelled.set()
    with pytest.raises(BridgeError,match='cancelled'):services.Service(s,{}).choose('trade_offer')
    assert not s.calls


@pytest.mark.parametrize('op',['fly','swim'])
def test_volume_commands_accept_observed_refs_or_relative_offsets(op):
    validate(op,{'ref':'visible_door'})
    validate(op,{'vertical_m':4,'seconds':150})
    with pytest.raises(BridgeError):validate(op,{'ref':'visible_door','vertical_m':1})
    with pytest.raises(BridgeError):validate(op,{'world_position':[1,2,3]})
    check_result({'navigation':{'movement_mode':'swim','source':'local_collision_3d'},
                  'elements':[{'control':'travel_destination','destination':'場所','value':'7'}]})


def test_three_dimensional_motor_and_physical_obstacles():
    import subprocess
    r=subprocess.run(['lua','tests/volume.lua'],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr


def test_atlas_public_route_and_history_hide_private_door_geometry():
    from copy import deepcopy
    route={'steps':[{'kind':'door','door':{'name':'Exit','anchor':[1,2,3]}}]}
    s=SimpleNamespace(atlas=SimpleNamespace(route_to=lambda ref:deepcopy(route)),observe=lambda **kw:None)
    assert workflows.atlas_query(s,{'route':'node_known'})['steps'][0]['door']=={'name':'Exit'}
    assert route['steps'][0]['door']['anchor']==[1,2,3]


def test_sequence_reads_postcondition_baseline_before_selecting_ui():
    s=Shop()
    s.latest_observation=s.observe()
    s.control.progress=lambda _:None
    # Reading inventory may change the UI revision/tooltip. The final selector
    # must run afterwards so it supplies a currently valid handle.
    original=s.command
    def command(op,args=None):
        if op=='inspect':s.revision+=1
        return original(op,args)
    s.command=command
    r=workflows.sequence(s,{'actions':[{'op':'choose','select':{'control':'trade_cancel'},
        'expect':{'inventory_delta':{'name':'Localized item','delta':0}}}]})
    assert r['action']['reason']=='completed'
    assert s.calls==['trade_cancel']
