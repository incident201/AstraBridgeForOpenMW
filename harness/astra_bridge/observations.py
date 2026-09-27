"""Small observations and a bounded cache of screenshots; maps are on demand."""
from pathlib import Path
import re


def compact(observation, before=None):
    keys = ('observation','state','paused','location','ui_mode','orientation','stats','body',
            'target_lock','messages','screenshot','local_map','screen','capture_sync','capture_backend')
    result = {k: observation[k] for k in keys if k in observation}
    scene = observation.get('scene', {})
    result['scene'] = {'objects': [{k: v for k,v in o.items() if k not in {'rect','aim_point','actions'}}
                                  for o in scene.get('objects', [])],
                       'sampling_limited': scene.get('sampling_limited', False)}
    ui = observation.get('ui', {})
    if observation.get('ui_mode') != 'Gameplay' or ui.get('modal'):
        result['ui'] = {k:v for k,v in ui.items() if k not in {'elements','text'}}
        # Dialogue text/topics are semantic; no viewport or substring truncation.
        if 'dialogue' not in ui: result['ui']['text'] = ui.get('text','')
        result['ui']['elements'] = [{k:v for k,v in e.items() if k not in {'rect','screen_visible'}}
                                    for e in ui.get('elements', []) if e.get('role') != 'text']
    result['terrain'] = {'passages': observation.get('terrain', {}).get('passages', [])}
    exploration = observation.get('exploration', {})
    result['exploration'] = {k:exploration[k] for k in ('supported','segment','current_node','persistent','loop_detected','svg','png') if k in exploration}
    if before:
        old = {o['ref']:o for o in before.get('scene',{}).get('objects',[]) if 'ref' in o}
        new = {o['ref']:o for o in scene.get('objects',[]) if 'ref' in o}
        result['changes'] = {'appeared': [o for o in result['scene']['objects'] if o.get('ref') not in old],
                             'no_longer_visible': [ref for ref in old if ref not in new]}
    return result


def present_response(result, full=False, before=None):
    if full or not isinstance(result, dict): return result
    result = dict(result)
    if 'observation' in result and isinstance(result['observation'], dict):
        result['observation'] = compact(result['observation'], before)
    elif isinstance(result.get('observation'), int):
        result = compact(result, before)
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
