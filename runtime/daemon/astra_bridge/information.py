"""Search and page public snapshots without discarding their contents."""
import json
from types import SimpleNamespace

from .protocol import BridgeError, number

SECTIONS = ('scene','ui','effects','combat','stats','body','terrain','exploration','messages')


def receipt_details(receipt, args):
    """Page a stored result without observing or advancing the running game."""
    if args.keys()-{'ref','view','section','query','page','limit'}:
        raise BridgeError('invalid_arguments')
    raw = receipt.get('response', {})
    view = args.get('view')
    if view is not None:
        views = raw.get('views', [])
        if type(view) is not int or not 0 <= view < len(views):
            raise BridgeError('invalid_view', views_total=len(views))
        observation = views[view].get('observation', {})
    else:
        observation = raw.get('observation', raw.get('final', raw))
    section = args.get('section', 'scene')
    if section in {'action','feedback'} and view is None:
        value = raw.get(section, {})
        if section == 'action' and isinstance(value,dict) and 'steps' in value:
            rows, meta = page_rows(value['steps'],args)
            value = {**value,'steps':rows,'steps_page':meta}
        selected = {'section':section,'data':value}
    else:
        if not isinstance(observation,dict) or 'observation' not in observation:
            raise BridgeError('result_has_no_observation')
        selected = details(SimpleNamespace(latest_observation=observation),
                           {k:v for k,v in {**args,'section':section}.items() if k not in {'ref','view'}})
    return {**{k:v for k,v in receipt.items() if k!='response'},
            'historical':True, **({'view':view} if view is not None else {}), 'response':selected}


def page_rows(rows, args, default=20):
    page, limit = args.get('page', 0), args.get('limit', default)
    number(page, 0, 1000000); number(limit, 1, 1000)
    if type(page) is not int or type(limit) is not int: raise BridgeError('invalid_arguments')
    query = args.get('query', '')
    if not isinstance(query, str): raise BridgeError('invalid_arguments')
    if query:
        rows = [r for r in rows if query.casefold() in json.dumps(r, ensure_ascii=False).casefold()]
    start = page * limit
    return rows[start:start+limit], {'total':len(rows), 'page':page, 'limit':limit, 'has_more':start+limit<len(rows)}


def details(session, args):
    if args.keys()-{'section','observation','query','page','limit'}: raise BridgeError('invalid_arguments')
    observation = session.latest_observation
    if not observation: raise BridgeError('observation_required')
    if args.get('observation', observation['observation']) != observation['observation']:
        raise BridgeError('stale_observation')
    section = args.get('section')
    if section not in SECTIONS:
        hint = 'inspect '+section if section in {'inventory','spells','journal','conversations','character'} else 'details --help'
        raise BridgeError('invalid_section', supported_sections=list(SECTIONS), next_command=hint)
    value = observation.get(section, {})
    result = {'observation':observation['observation'], 'section':section}
    if isinstance(value, list):
        result['items'], meta = page_rows(value,args); result.update(meta)
    elif isinstance(value, dict):
        result['data'] = dict(value)
        for key in ('objects','elements','passages','rays','nodes'):
            if key in value:
                result['data'][key], meta = page_rows(value[key],args)
                result[key+'_page'] = meta
    else: result['data'] = value
    return result


def query_ui(session, args):
    if args.keys()-{'query','page','limit','panel','role','control'}: raise BridgeError('invalid_arguments')
    value = session.command('ui')
    if getattr(session,'full_observations',False) and not any(args.get(k) for k in ('query','page','panel','role','control')):return value
    rows = value.get('elements', [])
    for key in ('panel','role','control'):
        if key in args: rows = [e for e in rows if e.get(key)==args[key]]
    value['elements'], meta = page_rows(rows,args)
    value.update(meta)
    # Avoid the same dialogue sidebar appearing twice.
    if 'dialogue' in value: value['dialogue'] = {k:v for k,v in value['dialogue'].items() if k!='topics'}
    if args.get('query') or args.get('page') or args.get('panel') or args.get('role') or args.get('control'):
        value.pop('text',None)
        if 'dialogue' in value:value['dialogue']={k:v for k,v in value['dialogue'].items() if k!='text'}
        value['text_details']='details ui'
    else:
        text=value.get('dialogue',{}).get('text',value.get('text',''))
        value.pop('text',None)
        if 'dialogue' in value:value['dialogue']={**value['dialogue'],'text':text[:1600]}
        else:value['text']=text[:1600]
        if len(text)>1600:value.update(text_characters=len(text),text_has_more=True,text_details='details ui')
    return value


def inspect_text(session,args):
    if args.keys()-{'view','topic','query','limit','page'}:raise BridgeError('invalid_arguments')
    native={k:v for k,v in args.items() if k in {'view','topic'}}
    value=session.command('inspect',native)
    key='entries' if 'entries' in value else 'topics'
    rows=value.get(key,[])
    if args['view']=='journal' or args['view']=='conversations' and args.get('topic'):
        page=1
        while len(rows)<value.get('total',0):
            part=session.command('inspect',{**native,'page':page});page+=1
            if not part.get('entries'):break
            rows.extend(part['entries'])
    value[key],meta=page_rows(rows,args)
    return {**value,**meta}
