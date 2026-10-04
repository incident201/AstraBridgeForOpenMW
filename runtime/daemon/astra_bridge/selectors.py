"""Fresh, declarative selection and postconditions; no arbitrary evaluation."""
import re
import math

from .outcomes import horizontal_displacement
from .protocol import BridgeError, number

REF_OPS={'focus','approach','interact','lock','track','strike','cast','target_info',
         'fly','swim','choose','edit','adjust','use_item','select_spell','select_enchanted'}
META={'select','bind','expect'}


def validate_step(step, bindings):
    params={k:v for k,v in step.items() if k not in META|{'op'}}
    op=step['op']
    selector=step.get('select')
    if selector is not None:
        if op not in REF_OPS or 'ref' in params or not isinstance(selector,dict):raise BridgeError('invalid_selector')
        if selector.keys()-{'source','name','contains','kind','actor_kind','panel','role','control','instance','nearest'}:raise BridgeError('invalid_selector')
        default='ui' if op in {'choose','edit','adjust'} else 'spells' if op=='select_spell' else 'inventory' if op in {'use_item','select_enchanted'} else 'scene'
        if selector.get('source',default)!=default:raise BridgeError('invalid_selector_source')
        if not any(k in selector for k in ('name','contains','control','instance','kind','actor_kind')):raise BridgeError('invalid_selector')
        if 'actor_kind' in selector and (default!='scene' or selector['actor_kind'] not in {'npc','creature'}):raise BridgeError('invalid_selector')
        for key,value in selector.items():
            if key=='nearest':
                if type(value) is not bool or default!='scene':raise BridgeError('invalid_selector')
            elif not isinstance(value,str) or not value:raise BridgeError('invalid_selector')
        params['ref']='selection_validation'
    ref=params.get('ref')
    if isinstance(ref,str) and ref.startswith('$'):
        if ref[1:] not in bindings:raise BridgeError('unknown_sequence_binding')
        params['ref']='selection_validation'
    if 'bind' in step:
        name=step['bind']
        if selector is None or not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',name):raise BridgeError('invalid_sequence_binding')
        bindings.add(name)
    expectation=step.get('expect',{})
    if not isinstance(expectation,dict) or expectation.keys()-{'ui_mode','location','location_changed','outcome','inventory_delta','gold_delta','min_horizontal_displacement_m'}:raise BridgeError('invalid_expectation')
    for key,value in expectation.items():
        if key=='location_changed':
            if type(value) is not bool:raise BridgeError('invalid_expectation')
        elif key=='min_horizontal_displacement_m':number(value,0,math.inf)
        elif key=='gold_delta':number(value,-1e12,1e12)
        elif key=='inventory_delta':
            if not isinstance(value,dict) or set(value)!={'name','delta'} or not isinstance(value['name'],str) or not value['name'] or type(value['delta']) is not int:raise BridgeError('invalid_expectation')
        elif not isinstance(value,str) or not value:raise BridgeError('invalid_expectation')
    return params


def resolve_step(session, step, bindings):
    params={k:v for k,v in step.items() if k not in META|{'op'}}
    if isinstance(params.get('ref'),str) and params['ref'].startswith('$'):
        params['ref']=bindings[params['ref'][1:]]
    selector=step.get('select')
    if selector is None:return params,None
    op=step['op']
    source=selector.get('source','ui' if op in {'choose','edit','adjust'} else 'spells' if op=='select_spell' else 'inventory' if op in {'use_item','select_enchanted'} else 'scene')
    if source=='scene':rows=session.observe(capture=False).get('scene',{}).get('objects',[])
    elif source=='ui':rows=session.command('ui').get('elements',[])
    else:rows=session.command('inspect',{'view':source}).get('spells' if source=='spells' else 'items',[])
    matches=[]
    for row in rows:
        if source=='ui' and not row.get('enabled'):continue
        label=row.get('name',row.get('text',''))
        if 'name' in selector and label!=selector['name']:continue
        if 'contains' in selector and selector['contains'].casefold() not in label.casefold():continue
        if any(row.get(k)!=selector[k] for k in ('kind','actor_kind','panel','role','control','instance') if k in selector):continue
        matches.append(row)
    if selector.get('nearest'):
        matches.sort(key=lambda r:r.get('distance_m',float('inf')))
        if len(matches)>1 and abs(matches[0].get('distance_m',0)-matches[1].get('distance_m',0))<.1:raise BridgeError('selection_ambiguous')
        matches=matches[:1]
    if len(matches)!=1:raise BridgeError('selection_ambiguous' if matches else 'selection_unavailable')
    row=matches[0];params['ref']=row['ref']
    if step.get('bind'):bindings[step['bind']]=row['ref']
    return params,{k:row[k] for k in ('ref','memory_ref','name','name_source','details_visible','actor_kind','text') if k in row}


def inventory_count(session,name):
    return sum(r.get('count',1) for r in session.command('inspect',{'view':'inventory'}).get('items',[]) if r.get('name')==name)


def check_expectation(session, expected, before, after, action, initial_count=None, summary=None):
    checks=[]
    for key,value in expected.items():
        if key=='min_horizontal_displacement_m':
            actual=summary.get('horizontal_displacement_m') if summary is not None else horizontal_displacement(action)
            checks.append({'condition':key,'expected':value,'actual':actual,'met':actual is not None and actual>=value,
                           **({'reason':'movement_not_comparable'} if actual is None else {})})
            continue
        if key=='outcome':actual=action.get('outcome')
        elif key=='location_changed':actual=before.get('location')!=after.get('location')
        elif key=='gold_delta':actual=after.get('stats',{}).get('gold',0)-before.get('stats',{}).get('gold',0)
        elif key=='inventory_delta':actual=inventory_count(session,value['name'])-initial_count;value=value['delta']
        else:actual=after.get(key)
        checks.append({'condition':key,'expected':value,'actual':actual,'met':actual==value})
    return checks
