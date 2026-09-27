"""Convenience actions over the actual open UI and its ordinary callbacks."""
import time
from .protocol import BridgeError, number
from .selectors import inventory_count


def validate_service(op,args):
    fields={'rest':{'hours','seconds'},'buy':{'name','quantity','max_total','instance','seconds'},
            'travel':{'destination','max_cost','seconds'}}
    if op not in fields or args.keys()-fields[op]:raise BridgeError('invalid_arguments')
    number(args.get('seconds',30),.2,float('inf'))
    if op=='rest':
        if type(args.get('hours')) is not int or args['hours']<1:raise BridgeError('invalid_arguments')
    if op=='buy':
        if not isinstance(args.get('name'),str) or not args['name']:raise BridgeError('invalid_arguments')
        if type(args.get('quantity',1)) is not int or args.get('quantity',1)<1:raise BridgeError('invalid_arguments')
        number(args.get('max_total'),0,1e12)
        if 'instance' in args and not isinstance(args['instance'],str):raise BridgeError('invalid_arguments')
    if op=='travel':
        if not isinstance(args.get('destination'),str) or not args['destination']:raise BridgeError('invalid_arguments')
        if 'max_cost' in args:number(args['max_cost'],0,1e12)


def control(rows,name, *, enabled=True):
    found=[e for e in rows if e.get('control')==name]
    if len(found)!=1:raise BridgeError('service_ui_missing_or_ambiguous')
    if enabled and not found[0].get('enabled'):raise BridgeError('ui_control_disabled')
    return found[0]


class Service:
    def __init__(self,session,args):
        self.session=session;self.deadline=time.monotonic()+args.get('seconds',30)
        self.mutations=0;self.phase='starting'

    def check(self):
        if self.session.control.cancelled.is_set():raise BridgeError('cancelled')
        if time.monotonic()>=self.deadline:raise BridgeError('service_time_limit')
        guard=getattr(self.session,'sequence_guard',None)
        if guard:
            obs=self.session.latest_observation or {};health=obs.get('stats',{}).get('health',{})
            if health and guard.get('stop_health_pct',0) and health['current']<=health['maximum']*guard['stop_health_pct']/100:raise BridgeError('health_low')
            if health and guard.get('stop_on_damage') and guard.get('health') is not None and health['current']<guard['health']:raise BridgeError('player_hurt')

    def rows(self):
        self.check()
        return self.session.command('ui').get('elements',[])

    def act(self,op,args):
        self.check();self.mutations+=1;self.phase=op
        return self.session.call(op,args)

    def choose(self,name):
        return self.act('choose',{'ref':control(self.rows(),name)['ref']})


def rest(s,args,context):
    before=s.observe(capture=False)
    if before.get('ui_mode')=='Gameplay':context.act('trigger',{'name':'Rest'})
    slider=control(context.rows(),'rest_hours')
    if args['hours']>slider['slider_max']+1:raise BridgeError('hours_exceed_rest_menu')
    context.act('adjust',{'ref':slider['ref'],'position':args['hours']-1})
    context.choose('rest_confirm')
    with s.record_ui():
        while True:
            context.check()
            current=s.observe(capture=False)
            if current.get('ui_mode') not in {'Rest','RestBed'}:break
            time.sleep(.05)
    hours=(current.get('game_time_seconds',0)-before.get('game_time_seconds',0))/3600
    return {'reason':'rest_complete' if hours>=args['hours']-.01 else 'rest_interrupted',
            'hours_requested':args['hours'],'hours_rested':round(hours,3)}


def buy(s,args,context):
    before=s.observe(capture=False);count=inventory_count(s,args['name'])
    rows=context.rows();control(rows,'trade_offer')
    if any(e.get('pending_trade') for e in rows):raise BridgeError('trade_cart_not_empty')
    matches=[e for e in rows if e.get('panel')=='merchant' and e.get('role')=='item' and e.get('text')==args['name']
             and (not args.get('instance') or e.get('instance')==args['instance'])]
    if len(matches)!=1:raise BridgeError('selection_ambiguous' if matches else 'selection_unavailable')
    item=matches[0];quantity=args.get('quantity',1)
    if quantity>item.get('count',0):raise BridgeError('quantity_unavailable')
    context.act('choose',{'ref':item['ref']})
    rows=context.rows()
    if any(e.get('control')=='quantity_slider' for e in rows):
        slider=control(rows,'quantity_slider')
        if quantity>slider['slider_max']+1:raise BridgeError('quantity_unavailable')
        context.act('adjust',{'ref':slider['ref'],'position':quantity-1})
        context.choose('quantity_confirm')
    elif quantity!=1:raise BridgeError('quantity_ui_unavailable')
    balance=control(context.rows(),'trade_balance',enabled=False)
    price=-int(balance['value'])
    if price<0:raise BridgeError('unexpected_trade_balance')
    if price>args['max_total'] or price>before.get('stats',{}).get('gold',0):
        context.choose('trade_cancel')
        return {'reason':'price_limit' if price>args['max_total'] else 'insufficient_gold','quoted_cost':price,'submitted':False}
    context.choose('trade_offer')
    after=s.observe(capture=False)
    gained=inventory_count(s,args['name'])-count
    cost=before.get('stats',{}).get('gold',0)-after.get('stats',{}).get('gold',0)
    return {'reason':'purchase_complete' if gained==quantity and cost==price else 'trade_unconfirmed',
            'quantity_received':gained,'gold_spent':cost,'quoted_cost':price,'submitted':True}


def travel(s,args,context):
    before=s.observe(capture=False)
    rows=context.rows()
    matches=[e for e in rows if e.get('control')=='travel_destination' and e.get('destination')==args['destination']]
    if len(matches)!=1:raise BridgeError('selection_ambiguous' if matches else 'destination_unavailable')
    row=matches[0];price=int(row['value'])
    if price>args.get('max_cost',float('inf')):return {'reason':'price_limit','quoted_cost':price,'submitted':False}
    if not row.get('enabled'):return {'reason':'insufficient_gold','quoted_cost':price,'submitted':False}
    context.act('choose',{'ref':row['ref']})
    after=s.observe(capture=False)
    cost=before.get('stats',{}).get('gold',0)-after.get('stats',{}).get('gold',0)
    arrived=after.get('location')!=before.get('location') and cost==price
    return {'reason':'travel_complete' if arrived else 'travel_unconfirmed','destination':args['destination'],
            'quoted_cost':price,'gold_spent':cost,'submitted':True}


def perform(session,op,args):
    validate_service(op,args);context=Service(session,args)
    start=session.observe(capture=False).get('simulation_seconds',0)
    session.batch_depth=getattr(session,'batch_depth',0)+1
    try:
        try:action={'rest':rest,'buy':buy,'travel':travel}[op](session,args,context)
        except BridgeError as exc:action={'reason':str(exc),'submitted':context.mutations>0,'phase':context.phase}
    finally:session.batch_depth-=1
    observation=session.observe()
    action.update(paused=True,elapsed=max(0,observation.get('simulation_seconds',start)-start))
    succeeded=action['reason'] in {'rest_complete','purchase_complete','travel_complete'}
    return {'action':action,'observation':observation,
            'feedback':{'status':'succeeded' if succeeded else 'interrupted','reason':action['reason'],'events':[]}}
