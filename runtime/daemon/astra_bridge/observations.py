"""Compact public snapshots; full observations are retained for explicit queries."""
from copy import deepcopy
from pathlib import Path
import re

from .responses import (compact_action, compact_body, compact_character, compact_effect,
                        compact_recording, compact_rows, text_is_visible)
from .response_context import COMBAT, SNAPSHOTS, context_for


def _effect_key(source):
    return source.get('name'), source.get('from_equipment', False), source.get('temporary', False)


PASSAGE_BEARINGS = {'front': 0, 'front_right': 45, 'right': 90, 'back_right': 135,
                    'back': 180, 'back_left': -135, 'left': -90, 'front_left': -45}


def _scene(scene, target_ref, *, snapshot, combat_context):
    objects = scene.get('objects', [])
    ordered = sorted(enumerate(objects), key=lambda pair: (
        pair[1].get('ref') != target_ref, pair[1].get('kind') not in {'actor', 'door'},
        not pair[1].get('in_reach', False), pair[0]
    ))
    # Combat needs the surrounding actors as well as the selected target.
    limit = 8 if snapshot or combat_context else 4
    rows = []
    for _, item in ordered[:limit]:
        row = {key: value for key, value in item.items()
               if key not in {'rect', 'aim_point', 'actions', 'center_bearing_deg', 'horizontal_distance_m'}
               and (combat_context or not key.startswith(('melee_', 'touch_')))}
        if not snapshot and item.get('ref') != target_ref:
            row.pop('memory_ref', None)
        if not combat_context and row.get('status') == 'active':
            row.pop('status')
        if row.get('height_change_m') == 0:
            row.pop('height_change_m')
        rows.append(row)
    result = {'objects': rows}
    if scene.get('sampling_limited'):
        result['sampling_limited'] = True
    if len(objects) > limit or scene.get('has_more'):
        result.update(total=max(len(objects), scene.get('total', 0)), has_more=True,
                      details='details scene --page N / --query TEXT')
    return result


def _terrain(terrain):
    passages = []
    for item in terrain.get('passages', []):
        row = dict(item)
        if row.get('clear_m') == row.get('distance_m'):
            row.pop('clear_m', None)
        if row.get('height_change_m') == 0:
            row.pop('height_change_m')
        if row.get('slope') == 'level':
            row.pop('slope')
        if row.get('bearing_deg') == PASSAGE_BEARINGS.get(row.get('direction')):
            row.pop('bearing_deg', None)
        passages.append(row)
    if passages:
        return {'passages': passages}
    return {'reason': terrain['reason']} if terrain.get('reason') else {}


def _messages(messages, ui):
    text = ui.get('dialogue', {}).get('text', ui.get('text', ''))
    rows = []
    for message in messages:
        # UI text is already readable in the dialogue/menu. Frame numbers are
        # useful for private deduplication, not for the next gameplay decision.
        if message.get('source') == 'ui_text' and text_is_visible(message.get('text'), text):
            continue
        row = {key: value for key, value in message.items() if key != 'frame'}
        if row not in rows:
            rows.append(row)
    return rows


def _compact_ui(ui, before):
    result = {key: value for key, value in ui.items()
              if key not in {'elements', 'text', 'dialogue', 'supported', 'blocked'}
              and value not in (None, '', [], {})}
    if ui.get('blocked'):
        result['blocked'] = True
    text = ui.get('dialogue', {}).get('text', ui.get('text', ''))
    old_text = before.get('dialogue', {}).get('text', before.get('text', ''))
    unchanged = ui.get('revision') and ui.get('revision') == before.get('revision') and text == old_text
    if unchanged:
        result.update(unchanged=True, details='details ui')
        return result
    # Native dialogue accumulates the greeting and earlier topics. A topic
    # selection should deliver its new answer, rather than repeat that history.
    shown_text = text[len(old_text):].lstrip() if old_text and text.startswith(old_text) else text
    if 'dialogue' in ui:
        result['dialogue'] = {key: value for key, value in ui['dialogue'].items()
                              if key not in {'text', 'topics'}}
        if shown_text:
            result['dialogue']['text'] = shown_text[:1600]
    elif shown_text:
        result['text'] = shown_text[:1600]
    if len(shown_text) > 1600:
        result.update(text_characters=len(shown_text), text_has_more=True, details='details ui')
    rows = [{key: value for key, value in item.items() if key not in {'description', 'rect'}}
            for item in ui.get('elements', []) if item.get('role') != 'text']
    if rows:
        result['elements'] = compact_rows(rows[:8], ui=True)
    if len(rows) > 8:
        result.update(elements_total=len(rows), elements_has_more=True,
                      details='ui --query TEXT / ui --page N')
    return result


def compact(observation, before=None, target_ref=None, *, combat_context=False, operation=None, context=None):
    previous = before or {}
    context = context or context_for(operation, {}, {}, previous, observation)
    combat_context = combat_context or context['combat']
    result = {key: observation[key] for key in (
        'observation', 'state', 'paused', 'location', 'ui_mode', 'screenshot', 'local_map'
    ) if key in observation}
    gameplay = observation.get('ui_mode') in {None, 'Gameplay'} and not observation.get('ui', {}).get('modal')
    if not context['scene'] and not context['physical']:
        result.pop('location', None)
        if result.get('state') in {'running', 'menu'}:
            result.pop('state', None)
        if result.get('paused') is True:
            result.pop('paused', None)
    orientation = observation.get('orientation', {})
    if orientation and gameplay and context['orientation']:
        result['orientation'] = {
            key: value for key, value in orientation.items()
            if key in {'heading_deg', 'pitch_deg'} or previous.get('orientation', {}).get(key) != value
        }
    stats = observation.get('stats', {})
    if stats and context['vitals']:
        changed_stats = {key: value for key, value in stats.items()
                         if (operation is None or key in {'health', 'magicka', 'fatigue'})
                         and previous.get('stats', {}).get(key) != value}
        for key, threshold in (('health', .25), ('fatigue', .1)):
            value = stats.get(key, {})
            if isinstance(value, dict) and value.get('maximum', 0) > 0:
                if value.get('current', 0) <= value['maximum'] * threshold:
                    changed_stats[key] = value
        if changed_stats:
            result['stats'] = changed_stats
    elif stats:
        health = stats.get('health', {})
        if (health.get('maximum', 0) > 0 and health.get('current', 0) <= health['maximum'] * .25
                and health != previous.get('stats', {}).get('health')):
            result['stats'] = {'health': health}
    if observation.get('body'):
        result['body'] = compact_body(observation['body'], previous.get('body'), equipment=context['equipment'])
        if not context['physical']:
            old_body = previous.get('body', {})
            defaults = {'on_ground': True, 'swimming': False, 'air_state': 'grounded',
                        'controls_enabled': True, 'can_move': True, 'looking_enabled': True,
                        'jumping_enabled': True, 'stance': 'nothing', 'vertical_speed_mps': 0}
            result['body'] = {key: value for key, value in result['body'].items()
                              if (context['selection'] or key not in {'weapon', 'selected_spell', 'selected_enchantment'})
                              and value != old_body.get(key, defaults.get(key, False))}
        if not gameplay and result['body'].get('air_state') in {None, 'grounded'}:
            result['body'] = {key: value for key, value in result['body'].items()
                              if key not in {'on_ground', 'swimming', 'air_state'}}
            if not result['body']:
                result.pop('body')
        if not result.get('body'):
            result.pop('body', None)
    screen = {key: value for key, value in observation.get('screen', {}).items()
              if key in {'width', 'height'}}
    if screen and context['orientation'] and any(previous.get('screen', {}).get(key) != value for key, value in screen.items()):
        result['screen'] = screen
    for key in ('target_lock', 'working_memory'):
        value = observation.get(key, {})
        active = value.get('status') != 'unlocked' if key == 'target_lock' else value.get('available')
        if value and (active or previous.get(key) != value and previous.get(key)):
            if not context['scene'] and not context['physical'] and value == previous.get(key):
                continue
            if key == 'target_lock' or previous.get(key) != value:
                result[key] = value
    if gameplay and context['scene']:
        result['scene'] = _scene(observation.get('scene', {}), target_ref,
                                 snapshot=operation in SNAPSHOTS, combat_context=combat_context)
    ui = observation.get('ui', {})
    if observation.get('ui_mode') != 'Gameplay' or ui.get('modal'):
        result['ui'] = _compact_ui(ui, previous.get('ui', {}))
    combat = observation.get('combat', {})
    old_combat = previous.get('combat', {})
    changed_combat = {}
    for key in ('weapon_info', 'castable') if context['equipment'] else ():
        value = combat.get(key, {})
        projected_value = {field: item for field, item in value.items()
                           if field not in {'effects', 'aim_assistance'}}
        old_value = {field: item for field, item in old_combat.get(key, {}).items()
                     if field not in {'effects', 'aim_assistance'}}
        if projected_value != old_value:
            if projected_value and projected_value.get('name') == old_value.get('name'):
                changed_combat[key] = {
                    field: item for field, item in projected_value.items()
                    if field not in old_value or old_value[field] != item
                }
                changed_combat[key].update({field: None for field in old_value if field not in projected_value})
            else:
                changed_combat[key] = projected_value
    if changed_combat:
        result['combat'] = changed_combat
        body = result.get('body', {})
        for field, selection in (('weapon', 'weapon_info'), ('selected_spell', 'castable'),
                                 ('selected_enchantment', 'castable')):
            if body.get(field) and body[field] == changed_combat.get(selection, {}).get('name'):
                body.pop(field)
    effects = observation.get('effects', [])
    old_effects = {_effect_key(source): source for source in previous.get('effects', [])}
    changed_effects = []
    for source in effects if context['effects'] else ():
        old_source = old_effects.get(_effect_key(source))
        if old_source is None or compact_effect(source) != compact_effect(old_source):
            changed_effects.append(compact_effect(source, old_source))
    if changed_effects:
        result['effects'] = changed_effects
    events = list(observation.get('events', []))
    current_effects = {_effect_key(source) for source in effects}
    for key, source in old_effects.items() if context['effects'] else ():
        if key not in current_effects and not any(
            event.get('kind') == 'effect_ended' and event.get('name') == source.get('name') for event in events
        ):
            events.append({'kind': 'effect_ended', 'name': source.get('name')})
    if events:
        result['events'] = events
    seen = {(item.get('text'), item.get('frame')) for item in previous.get('messages', [])}
    messages = _messages([item for item in observation.get('messages', [])
                          if (item.get('text'), item.get('frame')) not in seen], ui if 'ui' in result else {})
    if messages:
        result['messages'] = messages[-6:]
    if len(messages) > 6:
        result.update(messages_total=len(messages), messages_details='details messages --page N')
    terrain = _terrain(observation.get('terrain', {}))
    if terrain and gameplay and context['terrain']:
        result['terrain'] = terrain
    exploration = observation.get('exploration', {})
    projected = {key: value for key, value in exploration.items()
                 if key in {'segment', 'current_node', 'svg', 'png'} and value is not None}
    if exploration.get('loop_detected') and not previous.get('exploration', {}).get('loop_detected'):
        projected['loop_detected'] = True
    old_exploration = {key: value for key, value in previous.get('exploration', {}).items() if key in projected}
    if projected and context['scene'] and (operation in SNAPSHOTS or projected != old_exploration):
        result['exploration'] = projected
    return result


def remember_observation(observation, presented, previous=None, *, full=False):
    """Only delivered character/camera fields advance their comparison baseline.

    A UI-only result must not silently consume a stat, effect or equipment
    update before a later operation actually reports it to the agent.
    """
    if full:
        return deepcopy(observation)
    baseline = deepcopy(previous or {})
    for key in ('observation', 'state', 'paused', 'location', 'ui_mode', 'screenshot', 'scene', 'terrain', 'messages'):
        if key in observation:
            baseline[key] = deepcopy(observation[key])
    for section in ('stats', 'body', 'orientation', 'screen'):
        if section in presented:
            known = baseline.setdefault(section, {})
            raw = observation.get(section, {})
            for key, value in presented[section].items():
                known[key] = deepcopy(raw.get(key, value))
    if 'combat' in presented:
        known = baseline.setdefault('combat', {})
        for key, value in presented['combat'].items():
            known[key] = deepcopy(observation.get('combat', {}).get(key, value))
    raw_effects = {_effect_key(source): source for source in observation.get('effects', [])}
    known_effects = {_effect_key(source): source for source in baseline.get('effects', [])}
    if 'effects' in presented:
        # All sources were compared in this operation, even if only countdown
        # deltas were printed. Keep their full identities for the next delta.
        known_effects = raw_effects
    ended = {event.get('name') for event in presented.get('events', []) if event.get('kind') == 'effect_ended'}
    known_effects = {key: source for key, source in known_effects.items()
                     if key in raw_effects or source.get('name') not in ended}
    if known_effects or 'effects' in baseline:
        baseline['effects'] = deepcopy(list(known_effects.values()))
    for key in ('exploration', 'target_lock', 'working_memory'):
        if key in presented and key in observation:
            baseline[key] = deepcopy(observation[key])
    if 'ui' in presented or ('ui_mode' in observation and observation.get('ui_mode') != (previous or {}).get('ui_mode')):
        baseline['ui'] = deepcopy(observation.get('ui', {}))
    return baseline


def present_response(result, full=False, before=None, target_ref=None, operation=None, request_id=None, arguments=None):
    if full or not isinstance(result, dict):
        return result
    result = deepcopy(result)
    if not target_ref and isinstance(result.get('action'), dict):
        target_ref = result['action'].get('ref')
    combat_context = operation in COMBAT
    if isinstance(result.get('observation'), dict):
        action_context = {**(result.get('action') or {}),
                          'summary': result.get('summary') or {}, 'feedback': result.get('feedback') or {}}
        context = context_for(operation, action_context, arguments or {}, before or {}, result['observation'])
        result['observation'] = compact(result['observation'], before, target_ref,
                                        combat_context=combat_context, operation=operation, context=context)
    elif isinstance(result.get('observation'), int) and 'state' in result:
        return compact(result, before, target_ref, combat_context=combat_context, operation=operation)
    if 'views' in result and all(isinstance(view.get('observation'), dict) for view in result['views']):
        views = []
        previous = before or {}
        for index, view in enumerate(result['views']):
            observation = view['observation']
            landmarks = sorted(observation.get('scene', {}).get('objects', []),
                               key=lambda item: (item.get('kind') not in {'door', 'actor'}, item.get('distance_m', 0)))
            row = {'view': index, 'observation': observation.get('observation'),
                   **{key: value for key, value in observation.get('orientation', {}).items()
                      if key in {'heading_deg', 'pitch_deg'}},
                   'screenshot': observation.get('screenshot'),
                   'landmarks': [{key: item[key] for key in (
                       'ref', 'memory_ref', 'name', 'kind', 'actor_kind', 'details_visible',
                       'name_source', 'bearing_deg', 'distance_m'
                   ) if key in item} for item in landmarks[:3]]}
            seen = {(item.get('text'), item.get('frame')) for item in previous.get('messages', [])}
            messages = [item for item in observation.get('messages', [])
                        if (item.get('text'), item.get('frame')) not in seen]
            if messages:
                row.update(messages=messages[-3:])
                if len(messages) > 3:
                    row['messages_total'] = len(messages)
            views.append(row)
            previous = observation
        result['views'] = views
        result['details'] = f'action-result {request_id or "REQUEST_ID"} --view N --section scene / ui / messages'
    if isinstance(result.get('final'), dict):
        result['final'] = compact(result['final'], before, target_ref, operation=operation)
    if operation in {'status', 'inspect'} and 'player_name' in result:
        result = compact_character(result)
    if operation in {'record_start', 'record_stop', 'record_status'}:
        result = compact_recording(result)
    elif operation == 'finish_session':
        stages = result.get('stages', {})
        if 'recording' in stages:
            stages['recording'] = compact_recording(stages['recording'])
    elif operation == 'status' and 'recording' in result:
        result['recording'] = compact_recording(result['recording'])
        active = result.get('active_action')
        if isinstance(active, dict) and isinstance(active.get('navigation'), dict):
            active['navigation'] = compact_action({'action': {'navigation': active['navigation']}})['action'].get('navigation', {})
    if operation == 'atlas':
        if 'nodes' in result and 'segment' in result:
            # The explicit --list query supplies the global catalog and links.
            result.pop('spaces', None)
            result.pop('transitions', None)
        for key in ('supported', 'persistent', 'source', 'not_a_full_map', 'sampled_path'):
            if result.get(key) not in (None, False):
                result.pop(key, None)
        for key in ('archived', 'loop_detected'):
            if result.get(key) is False:
                result.pop(key)
        for row in result.get('nodes', []):
            for key in ('names', 'landmarks', 'screenshots', 'untraversed_directions'):
                if not row.get(key):
                    row.pop(key, None)
            if row.get('route_distance_m') is None:
                row.pop('route_distance_m', None)
            if row.get('location') == result.get('location'):
                row.pop('location')
    if operation in {'ui', 'inspect'}:
        if result.get('supported') is True:
            result.pop('supported')
        if isinstance(result.get('combat'), dict) and result['combat'].get('supported') is True:
            result['combat'].pop('supported')
        for key in ('elements', 'items', 'spells'):
            if key in result:
                result[key] = compact_rows(result[key], ui=key == 'elements')
        if operation == 'ui':
            if result.get('supported') is True:
                result.pop('supported')
            if result.get('blocked') is False:
                result.pop('blocked')
            if result.get('text') == '':
                result.pop('text')
    if operation == 'pick':
        for item in result.get('objects', []):
            for key in ('rect', 'actions', 'horizontal_distance_m', 'center_bearing_deg'):
                item.pop(key, None)
    if operation == 'knowledge' and result.get('source') == 'observed_object_memory' and result.get('historical'):
        for item in result.get('objects', []):
            if item.get('source') == result['source']:
                item.pop('source')
            if item.get('name_source') == 'remembered':
                item.pop('name_source')
            if item.get('notes_total') == 0:
                item.pop('notes_total')
    return compact_action(result, request_id)


def prune_screenshots(directory, memory, keep=128):
    """Delete only generated cache files, protecting explicit place memories."""
    directory = Path(directory)
    pinned = {Path(v['screenshot']).resolve() for p in memory.data.get('places', [])
              for v in p.get('views', []) if v.get('screenshot')}
    pinned |= {Path(p['local_map']).resolve() for p in memory.data.get('places', []) if p.get('local_map')}
    frames, maps = [], []
    for p in directory.iterdir():
        if not p.is_file() or p.resolve() in pinned: continue
        if re.fullmatch(r'[a-f0-9]{8}-\d+(?:-map)?\.png', p.name): frames.append(p)
        elif re.fullmatch(r'(?:[a-f0-9]{8}-\d+(?:-atlas)?|space_[a-zA-Z0-9_]+-archive)\.(?:svg|png)',p.name): maps.append(p)
    removed = 0
    for group, limit in ((frames, keep), (maps, 8)):
        for p in sorted(group,key=lambda p:p.stat().st_mtime,reverse=True)[limit:]:
            p.unlink(missing_ok=True); removed += 1
    return {'removed':removed,'recent_limit':keep,'pinned':len(pinned)}
