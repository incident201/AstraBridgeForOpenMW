"""Public-action compositions with fresh selectors and explicit stopping results."""
import math
import re

from .protocol import BridgeError, number, validate, ACTION_DEFAULTS
from . import selectors


SEQUENCE_OPS = {'act','look','go','walk','revisit','return_to','approach','interact','move_local',
                'use_item','select_spell','select_enchanted','cast','strike','chain','wait_until',
                'trigger','choose','edit','adjust','focus','fly','swim','target_info','rest','buy','travel','unlock','lock'}


def validate_sequence(args):
    if args.keys()-{'actions','max_seconds','stop_health_pct','stop_on_damage'}: raise BridgeError('invalid_arguments')
    steps = args.get('actions')
    if not isinstance(steps,list) or not steps: raise BridgeError('invalid_arguments')
    number(args.get('max_seconds',60),.02,math.inf)
    number(args.get('stop_health_pct',0),0,100)
    if type(args.get('stop_on_damage',True)) is not bool: raise BridgeError('invalid_arguments')
    bindings=set()
    for step in steps:
        if not isinstance(step,dict) or step.get('op') not in SEQUENCE_OPS: raise BridgeError('invalid_sequence_step')
        op=step['op']; params=selectors.validate_step(step,bindings)
        if op in {'rest','buy','travel'}:
            from .services import validate_service
            validate_service(op,params);continue
        if op in {'use_item','select_spell','select_enchanted'} and 'name' in params:
            if params.keys()!={'name'} or not isinstance(params['name'],str) or not params['name']: raise BridgeError('invalid_arguments')
        elif op in {'revisit','return_to'}:
            if params.keys()-{'ref','run','seconds','under_fire'} or not isinstance(params.get('ref'),str): raise BridgeError('invalid_arguments')
            validate('go',{**params,'ref':'waypoint_validation'})
        else: validate(op,params)


def resolve_owned(session, op, params):
    if 'name' not in params: return params
    view='spells' if op=='select_spell' else 'inventory'
    items=session.command('inspect',{'view':view}).get('spells' if view=='spells' else 'items',[])
    matches=[x for x in items if x['name']==params['name']]
    if len(matches)!=1: raise BridgeError('selection_ambiguous' if matches else 'selection_unavailable')
    return {'ref':matches[0]['ref']}


def sequence(session, args):
    validate_sequence(args)
    steps=[];elapsed=0.;reason='completed';completed=0;events=[];bindings={}
    observation=session.observe(capture=False)
    health=observation.get('stats',{}).get('health',{}).get('current')
    start_clock=observation.get('simulation_seconds')
    previous_guard=getattr(session,'sequence_guard',None)
    session.sequence_guard={'stop_on_damage':args.get('stop_on_damage',True),'stop_health_pct':args.get('stop_health_pct',0),'health':health}
    if start_clock is not None:session.sequence_guard['deadline']=start_clock+args.get('max_seconds',60)
    session.batch_depth=getattr(session,'batch_depth',0)+1
    try:
        for index,step in enumerate(args['actions']):
            if session.control.cancelled.is_set(): reason='cancelled';break
            remaining=args.get('max_seconds',60)-elapsed
            if remaining<.02: reason='sequence_time_limit';break
            session.control.progress({'phase':'sequence','completed_actions':completed,'total_actions':len(args['actions']),'step_index':index+1,'sequence_elapsed':elapsed})
            op=step['op']
            minimum=.5 if op in {'go','walk','chain','revisit','return_to'} else .2 if op in {'fly','swim','rest','buy','travel'} else .02
            if remaining<minimum:reason='sequence_time_limit';break
            try:
                expectation=step.get('expect',{})
                initial_count=selectors.inventory_count(session,expectation['inventory_delta']['name']) if 'inventory_delta' in expectation else None
                params,selected=selectors.resolve_step(session,step,bindings)
                if op in ACTION_DEFAULTS:
                    field='max_seconds' if op=='chain' else 'seconds'
                    params[field]=min(params.get(field,ACTION_DEFAULTS[op]),remaining)
                if op in {'use_item','select_spell','select_enchanted'}: params=resolve_owned(session,op,params)
                before_step=observation
                r=session.call(op,params)
            except BridgeError as exc:
                reason=str(exc);steps.append({'operation':op,'reason':reason,'submitted':False});break
            a=r.get('action',{});elapsed+=a.get('elapsed',0)
            steps.append({'operation':op,**a})
            if selected:steps[-1]['selected']=selected
            observation=r.get('observation',observation)
            events.extend(observation.get('events',[]))
            if start_clock is not None:elapsed=max(elapsed,observation.get('simulation_seconds',start_clock)-start_clock)
            if a.get('reason') in {'health_low','player_hurt','sequence_time_limit'}:reason=a['reason'];break
            status=r.get('feedback',{}).get('status')
            if status in {'blocked','failed','rejected','partial','interrupted'}:
                reason=r['feedback'].get('reason') or a.get('reason') or status;break
            checks=selectors.check_expectation(session,expectation,before_step,observation,a,initial_count)
            if checks:steps[-1]['checks']=checks
            if any(not c['met'] for c in checks):reason='expectation_failed';break
            completed+=1
            h=observation.get('stats',{}).get('health',{})
            if h and args.get('stop_health_pct',0) and h['current']<=h['maximum']*args['stop_health_pct']/100:
                reason='health_low';break
            if health is not None and h and args.get('stop_on_damage',True) and h['current']<health:
                reason='player_hurt';break
            health=h.get('current',health)
            session.sequence_guard['health']=health
            # A planned interaction may open UI. Other steps may not silently
            # continue into an unexpected menu or a different cell.
            if (observation.get('ui_mode')!='Gameplay' or observation.get('ui',{}).get('modal')) and op not in {'interact','choose','trigger','use_item','edit','adjust','rest','buy','travel'}:
                reason='ui_input_required' if observation.get('ui',{}).get('modal') else 'ui_open';break
    finally:
        session.batch_depth-=1
        session.sequence_guard=previous_guard
    return {'action':{'reason':reason,'elapsed':elapsed,'steps':steps,'completed_actions':completed,
                      'total_actions':len(args['actions']),'paused':True,'bindings':bindings},
            'observation':session.observe(),'feedback':{'status':'succeeded' if reason=='completed' else 'interrupted','reason':reason,'events':events}}


def read_document(session,args):
    """Only the currently opened native document; never inventory record text."""
    params={k:v for k,v in args.items() if k not in {'all','search'}}
    if 'all' in args and type(args['all']) is not bool:raise BridgeError('invalid_arguments')
    if 'search' in args and (not isinstance(args['search'],str) or not args['search']):raise BridgeError('invalid_arguments')
    if args.get('all') and args.get('search'): raise BridgeError('invalid_arguments')
    part=session.command('read',params)
    if not args.get('all') and not args.get('search'):return part
    text=part['text'];ref=part['ref'];offset=part['offset']
    while not part['eof']:
        if session.control.cancelled.is_set():raise BridgeError('cancelled')
        part=session.command('read',{'ref':ref,'offset':part['next_offset'],'limit':8000})
        text+=part['text']
    result={**part,'offset':offset,'text':text}
    if hasattr(session,'knowledge'):session.knowledge.ingest('read',result)
    if args.get('search'):
        query=args['search']
        if not isinstance(query,str) or not query:raise BridgeError('invalid_arguments')
        matches=[{'offset':offset+m.start(),'text':text[max(0,m.start()-120):m.end()+200]}
                 for m in re.finditer(re.escape(query),text,re.IGNORECASE)]
        result.pop('text');result['matches']=matches
    return result


def repair(session,args):
    if args.keys()-{'name','attempts','condition_pct','instance'} or not isinstance(args.get('name'),str):raise BridgeError('invalid_arguments')
    if 'instance' in args and (not isinstance(args['instance'],str) or not args['instance'].startswith('instance_')):raise BridgeError('invalid_arguments')
    attempts=args.get('attempts',1);number(attempts,1,math.inf)
    if type(attempts) is not int:raise BridgeError('invalid_arguments')
    threshold=number(args.get('condition_pct',100),0,100)
    results=[];reason='attempt_limit';last_condition=None
    session.batch_depth=getattr(session,'batch_depth',0)+1
    try:
        for _ in range(attempts):
            if session.control.cancelled.is_set():reason='cancelled';break
            ui=session.command('ui')
            rows=[e for e in ui.get('elements',[]) if e.get('panel')=='repair' and e.get('role')=='item' and e.get('text')==args['name']]
            if args.get('instance'):rows=[e for e in rows if e.get('instance')==args['instance']]
            if not any(e.get('panel')=='repair' for e in ui.get('elements',[])):reason='repair_ui_closed';break
            if not rows:reason='item_not_in_repair_list';break
            if len(rows)!=1:reason='selection_ambiguous';break
            row=rows[0]
            if row.get('condition_current',0)>=row.get('condition_max',1)*threshold/100:reason='condition_met';break
            if not row.get('enabled'):reason='repair_unavailable';break
            before=row.get('condition_current')
            r=session.call('choose',{'ref':row['ref']})
            after=session.command('ui')
            remaining=[e for e in after.get('elements',[]) if e.get('panel')=='repair' and e.get('role')=='item' and e.get('text')==args['name']]
            if args.get('instance'):remaining=[e for e in remaining if e.get('instance')==args['instance']]
            last_condition=remaining[0].get('condition_current') if len(remaining)==1 else None
            results.append({'before':before,'after':last_condition,'reason':r.get('feedback',{}).get('reason')})
            if last_condition is not None and last_condition>=row.get('condition_max',1)*threshold/100:
                reason='condition_met';break
            if not remaining:
                # RepairWindow removes a row once its item is fully repaired.
                # A closed/tool-selection window is not evidence of success.
                reason='condition_met' if any(e.get('panel')=='repair' for e in after.get('elements',[])) else 'repair_ui_closed'
                break
    finally:session.batch_depth-=1
    return {'action':{'reason':reason,'attempts':len(results),'steps':results},'observation':session.observe(),
            'feedback':{'status':'succeeded' if reason=='condition_met' else 'partial','reason':reason,'events':[]}}


def atlas_query(session,args):
    if args.keys()-{'radius_m','list','space','query','page','limit','level','map','route','history'}:raise BridgeError('invalid_arguments')
    atlas=session.atlas
    if args.get('history'):return atlas.outcome_history(args)
    if args.get('list'):return {'spaces':atlas.catalog(),'transitions':atlas.transitions()}
    session.observe(capture=False)
    if args.get('route'):
        route=atlas.route_to(args['route'])
        if not route:raise BridgeError('recorded_route_unavailable')
        for step in route['steps']:step.get('door',{}).pop('anchor',None)
        return route
    page=args.get('page',0);limit=args.get('limit',20)
    number(page,0,1000000);number(limit,1,1000)
    if type(page) is not int or type(limit) is not int:raise BridgeError('invalid_arguments')
    space=args.get('space')
    if space and not atlas.graph_for(space):raise BridgeError('unknown_map_space')
    if 'query' in args:
        if not isinstance(args['query'],str):raise BridgeError('invalid_arguments')
        return atlas.search(args['query'],space,page,limit,args.get('level'))
    active=atlas.segment
    try:
        if space:atlas.segment=space
        path=session.runtime/'screenshots'/'atlas-current.svg' if args.get('map') else None
        result=atlas.present(path,number(args.get('radius_m',35),.1,math.inf),archived=atlas.segment!=active,
                             page=page,limit=limit,level=args.get('level'))
        for item in result.get('spaces',[]):item['current']=item['ref']==active
        return result
    finally:atlas.segment=active


def navigate(session,args):
    """Try at most three different learned legs within one total action budget."""
    total=0;steps=[];replans=0
    budget=number(args.get('seconds',60),.02,math.inf)
    while True:
        try:result=_navigate_once(session,{**args,'seconds':budget-total})
        except BridgeError as exc:
            if not replans:raise
            result['action']['reason']=str(exc);result['feedback'].update(status='interrupted',reason=str(exc));break
        total+=result['action'].get('elapsed',0);steps.extend(result['action'].get('steps',[]))
        if result['action']['reason'] not in {'blocked','no_route_progress','repeated_positions','repeated_obstruction','no_progress','no_path','known_door_not_visible','activation_unconfirmed'} or replans>=2 or budget-total<.5:break
        if not session.atlas.route_to(args['ref']):break
        replans+=1
    result['action'].update(elapsed=total,steps=steps,replans=replans)
    return result


def _navigate_once(session,args):
    if args.keys()-{'ref','run','seconds','under_fire'} or not isinstance(args.get('ref'),str):raise BridgeError('invalid_arguments')
    budget=number(args.get('seconds',60),.02,math.inf)
    validate('go',{'ref':'waypoint_validation','seconds':max(.5,budget),
                   **{k:v for k,v in args.items() if k in {'run','under_fire'}}})
    session.observe(capture=False)
    plan=session.atlas.route_to(args['ref'])
    if not plan:raise BridgeError('recorded_route_unavailable')
    elapsed=0.;results=[];reason='arrived';seen_positions=set()
    session.batch_depth=getattr(session,'batch_depth',0)+1
    try:
        for step in plan['steps']:
            if session.control.cancelled.is_set():reason='cancelled';break
            origin={'space':session.atlas.segment,'pose':list(session.atlas.current()['pose'])}
            if step['kind']=='walk':
                while True:
                    if session.control.cancelled.is_set():reason='cancelled';break
                    remaining=budget-elapsed
                    if remaining<.5:reason='step_limit';break
                    atlas=session.atlas;space,node=atlas.find_node(step['ref'])
                    if space!=atlas.current():reason='unexpected_location';break
                    pose=space['pose']
                    if math.dist(node['p'],pose)<.36:break
                    signature=(node['ref'],tuple(round(v,1) for v in pose))
                    if signature in seen_positions:reason='no_progress';break
                    seen_positions.add(signature)
                    route=atlas.travelled_route(node)
                    goal=node['p'];chunk=[];length=0;previous=pose
                    if route:
                        for point in route:
                            length+=math.dist(previous,point);previous=point
                            if length>60 or len(chunk)>=400:break
                            chunk.append(point)
                        if chunk:goal=chunk[-1]
                    if math.dist(goal,pose)>=100:reason='recorded_route_unavailable';break
                    offset=[round(a-b,4) for a,b in zip(goal,pose)]
                    offsets=[[round(a-b,4) for a,b in zip(p,pose)] for p in chunk] if chunk else None
                    marker=session.command('mark',_atlas_offset=offset,_atlas_route=offsets)['ref']
                    r=session.call('go',{'ref':marker,'seconds':remaining,**{k:v for k,v in args.items() if k in {'run','under_fire'}}})
                    a=r['action'];results.append(a);elapsed+=a.get('elapsed',0)
                    session.atlas.record_outcome(step,origin,a)
                    if a.get('reason')!='arrived':reason=a.get('reason','interrupted');break
                    if math.dist(goal,node['p'])<.04:break
                if reason!='arrived':break
            else:
                remaining=budget-elapsed
                if remaining<.1:reason='step_limit';break
                from .doors import reacquire
                door,spent,matching=reacquire(session,step,remaining)
                elapsed+=spent;remaining=budget-elapsed
                if not door:
                    reason=matching
                    session.atlas.record_outcome(step,origin,{'reason':reason});break
                if remaining<.1:reason='step_limit';break
                r=session.call('interact',{'ref':door['ref'],'approach':True,'seconds':remaining,
                                          **{k:v for k,v in args.items() if k in {'run','under_fire'}}})
                a=r['action'];results.append(a);elapsed+=a.get('elapsed',0)
                session.atlas.record_outcome(step,origin,a)
                if a.get('outcome')!='location_changed':reason='activation_unconfirmed' if a.get('reason')=='completed' else a.get('reason','activation_unconfirmed');break
                if session.atlas.segment!=step['to_space']:reason='unexpected_location';break
    finally:session.batch_depth-=1
    obs=session.observe()
    return {'action':{'reason':reason,'elapsed':elapsed,'steps':results,'ref':plan['destination'],'paused':True},
            'observation':obs,'feedback':{'status':'succeeded' if reason=='arrived' else 'interrupted','reason':reason,'events':[]}}
