"""Small observations and a bounded cache of screenshots; maps are on demand."""
from pathlib import Path
import re


def compact(observation, before=None):
    keys = ('observation','state','paused','location','ui_mode','orientation','stats','body',
            'target_lock','messages','events','screenshot','local_map','screen')
    result = {k: observation[k] for k in keys if k in observation}
    scene = observation.get('scene', {})
    result['scene'] = {'objects': [{k: v for k,v in o.items() if k not in {'rect','aim_point','actions'}}
                                  for o in scene.get('objects', [])],
                       'sampling_limited': scene.get('sampling_limited', False)}
    ui = observation.get('ui', {})
    if observation.get('ui_mode') != 'Gameplay' or ui.get('modal'):
        result['ui'] = {k:v for k,v in ui.items() if k not in {'elements','text','dialogue','supported'}}
        old_ui=(before or {}).get('ui',{})
        unchanged=ui.get('revision') and ui.get('revision')==old_ui.get('revision')
        text=ui.get('dialogue',{}).get('text',ui.get('text',''))
        if unchanged:
            result['ui'].update(unchanged=True,details='details ui')
        else:
            if 'dialogue' in ui:
                result['ui']['dialogue']={k:v for k,v in ui['dialogue'].items() if k not in {'text','topics'}}
                result['ui']['dialogue']['text']=text[:1600]
            else:result['ui']['text']=text[:1600]
            if len(text)>1600:result['ui'].update(text_characters=len(text),text_has_more=True,details='details ui')
            rows=[{k:v for k,v in e.items() if k not in {'rect','screen_visible','description'}}
                  for e in ui.get('elements',[]) if e.get('role')!='text']
            result['ui']['elements']=rows[:20]
            if len(rows)>20:result['ui'].update(elements_total=len(rows),elements_has_more=True,details='ui --query TEXT / ui --page N')
    combat=observation.get('combat',{})
    if combat:
        result['combat']={k:v for k,v in combat.items() if k in {'weapon_info','castable'}}
        for key in result['combat']:
            result['combat'][key]={k:v for k,v in result['combat'][key].items() if k not in {'effects','aim_assistance'}}
    if observation.get('effects'):
        result['effects']=[{**{k:v for k,v in e.items() if k!='effects'},
                            'effects':[{k:v for k,v in effect.items() if k!='description'} for effect in e.get('effects',[])]}
                           for e in observation['effects']]
    if before:
        seen={(m.get('text'),m.get('frame')) for m in before.get('messages',[])}
        result['messages']=[m for m in result.get('messages',[]) if (m.get('text'),m.get('frame')) not in seen]
    result['terrain'] = {'passages': observation.get('terrain', {}).get('passages', [])}
    exploration = observation.get('exploration', {})
    result['exploration'] = {k:exploration[k] for k in ('supported','segment','current_node','persistent','loop_detected','svg','png') if k in exploration}
    if before:
        old = {o['ref']:o for o in before.get('scene',{}).get('objects',[]) if 'ref' in o}
        new = {o['ref']:o for o in scene.get('objects',[]) if 'ref' in o}
        result['changes'] = {'appeared': [o['ref'] for o in result['scene']['objects'] if o.get('ref') not in old],
                             'no_longer_visible': [ref for ref in old if ref not in new]}
    return result


def present_response(result, full=False, before=None):
    if full or not isinstance(result, dict): return result
    result = dict(result)
    if 'observation' in result and isinstance(result['observation'], dict):
        result['observation'] = compact(result['observation'], before)
    elif isinstance(result.get('observation'), int) and 'state' in result:
        result = compact(result, before)
    action=result.get('action')
    if isinstance(action,dict):
        result['action']=action=dict(action)
        action.pop('body',None)  # the canonical observation already contains it
        if action.get('reason') in {'arrived','within_reach','focused','completed','duration','condition_met'} and isinstance(action.get('navigation'),dict):
            action['navigation']={k:v for k,v in action['navigation'].items() if k in {'status','remaining_m','recovery_count','reason','blocked_by'}}
    if isinstance(action,dict) and len(action.get('steps',[]))>8:
        result['action']={**action,'steps':action['steps'][-8:],'steps_total':len(action['steps']),
                          'steps_has_more':True,'details':'action-result REQUEST_ID --full'}
    if 'views' in result:
        result['views'] = [{**v,'observation':compact(v['observation'])} if isinstance(v.get('observation'),dict) else v for v in result['views']]
    if isinstance(result.get('final'),dict): result['final'] = compact(result['final'])
    return result


def prune_screenshots(directory, memory, keep=128):
    """Delete only generated cache files, protecting explicit place memories."""
    directory = Path(directory)
    pinned = {Path(v['screenshot']).resolve() for p in memory.data.get('places', [])
              for v in p.get('views', []) if v.get('screenshot')}
    pinned |= {Path(p['local_map']).resolve() for p in memory.data.get('places', []) if p.get('local_map')}
    frames, maps = [], []
    for p in directory.iterdir():
        if not p.is_file() or p.resolve() in pinned: continue
        if re.fullmatch(r'[a-f0-9]{8}-\d+\.png', p.name): frames.append(p)
        elif re.fullmatch(r'(?:[a-f0-9]{8}-\d+(?:-atlas)?|space_[a-zA-Z0-9_]+-archive)\.(?:svg|png)',p.name): maps.append(p)
    removed = 0
    for group, limit in ((frames, keep), (maps, 8)):
        for p in sorted(group,key=lambda p:p.stat().st_mtime,reverse=True)[limit:]:
            p.unlink(missing_ok=True); removed += 1
    return {'removed':removed,'recent_limit':keep,'pinned':len(pinned)}
