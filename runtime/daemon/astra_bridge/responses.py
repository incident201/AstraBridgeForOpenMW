"""Presentation of public action results; raw receipts remain unchanged."""
from copy import deepcopy

from .outcomes import summarize


SUCCESS_REASONS = {'arrived', 'within_reach', 'focused', 'completed', 'duration', 'condition_met'}
NAVIGATION_KEYS = {
    'reason', 'blocked_by', 'remaining_m', 'goal_distance_m', 'goal_height_change_m',
    'recovery_count', 'replans', 'stalled_seconds', 'movement_mode', 'path_endpoint_gap_m',
}


def compact_body(body, before=None, *, equipment=True):
    """Keep physical state and restrictions, with ordinary controls as defaults."""
    previous = before or {}
    result = {}
    for key, value in body.items():
        if key in {'weapon', 'selected_spell', 'selected_enchantment'}:
            if equipment and value != previous.get(key):
                result[key] = value
        elif key in {'can_move', 'controls_enabled', 'looking_enabled', 'jumping_enabled'}:
            if value is False or previous.get(key) is False and value is True:
                result[key] = value
        elif key in {'on_ground', 'swimming', 'air_state'}:
            result[key] = value
        elif key == 'vertical_speed_mps':
            if value or body.get('air_state') not in {None, 'grounded', 'swimming'}:
                result[key] = value
        elif key == 'stance':
            if value != 'nothing' or previous.get(key) not in {None, 'nothing'}:
                result[key] = value
        elif value:
            result[key] = value
    # Report cleared selections explicitly; absence otherwise means no update.
    if equipment:
        for key in ('weapon', 'selected_spell', 'selected_enchantment'):
            if previous.get(key) and not body.get(key):
                result[key] = None
    return result


def compact_navigation(navigation, reason=None):
    result = {key: value for key, value in navigation.items()
              if key in NAVIGATION_KEYS and value is not None}
    if navigation.get('status') and navigation['status'] != reason:
        result['status'] = navigation['status']
    for key in ('recovery_count', 'stalled_seconds', 'goal_height_change_m'):
        if result.get(key) == 0:
            result.pop(key)
    if result.get('replans', 0) <= 1:
        result.pop('replans', None)
    if result.get('movement_mode') == 'walk':
        result.pop('movement_mode')
    if reason in SUCCESS_REASONS:
        for key in ('remaining_m', 'goal_distance_m', 'goal_height_change_m', 'path_endpoint_gap_m'):
            result.pop(key, None)
    elif result.get('path_endpoint_gap_m', 0) <= navigation.get('arrival_tolerance_m', 0):
        result.pop('path_endpoint_gap_m', None)
    if result.get('reason') == reason:
        result.pop('reason', None)
    return result


def compact_effect(source, previous=None):
    result = {key: value for key, value in source.items()
              if key != 'effects' and value not in (None, False, '', [], {})}
    result['effects'] = [
        {key: value for key, value in effect.items()
         if key != 'description' and value is not None
         and not (value is False or value == '')}
        for effect in source.get('effects', [])
    ]
    if previous is not None:
        old = compact_effect(previous)

        def identity(effect):
            return tuple(effect.get(key) for key in ('name', 'affected_attribute', 'affected_skill'))
        old_rows = {identity(effect): effect for effect in old.get('effects', [])}
        new_rows = {identity(effect): effect for effect in result['effects']}
        same_source = {key: value for key, value in result.items() if key != 'effects'} == {
            key: value for key, value in old.items() if key != 'effects'
        }
        if same_source and old_rows.keys() == new_rows.keys():
            # Countdown updates need identity and time, not repeated strengths,
            # original duration and source flags. Structural changes use a snapshot.
            def static(row):
                return {key: value for key, value in row.items() if key != 'remaining_seconds'}

            if all(static(row) == static(old_rows[key]) for key, row in new_rows.items()):
                rows = [{**{key: value for key, value in row.items()
                            if key in {'name', 'affected_attribute', 'affected_skill', 'harmful'}},
                         'remaining_seconds': row.get('remaining_seconds')}
                        for key, row in new_rows.items()
                        if row.get('remaining_seconds') != old_rows[key].get('remaining_seconds')]
                if rows:
                    result = {'name': source.get('name'), 'effects': rows}
                    if source.get('from_equipment'):
                        result['from_equipment'] = True
    return result


def compact_rows(rows, *, ui=False):
    """Remove redundant display metadata, without truncating requested content."""
    result = []
    for row in rows:
        item = dict(row)
        for key in ('supported', 'screen_visible') if ui else ('supported',):
            if item.get(key) is True:
                item.pop(key)
        for key in ('equipped', 'selected'):
            if item.get(key) is False:
                item.pop(key)
        for key in ('effects', 'description'):
            if item.get(key) in ('', [], None):
                item.pop(key, None)
        if ui:
            item.pop('rect', None)
        result.append(item)
    return result


def compact_recording(value):
    if not isinstance(value, dict):
        return value
    keys = {'recording', 'capturing', 'path', 'duration', 'frames', 'fps',
            'width', 'height', 'audio', 'error', 'upload_ready', 'encoder',
            'hardware_accelerated', 'encoder_fallback'}
    return {key: item for key, item in value.items()
            if key in keys and item is not None and item != ''}


def compact_character(result):
    result = deepcopy(result)
    if 'stats' in result:
        result['stats'].pop('attribute_details', None)
        for row in result['stats'].get('skills', []):
            for key in ('base', 'modifier', 'damage', 'progress_percent'):
                row.pop(key, None)
    if 'body' in result:
        result['body'] = compact_body(result['body'])
    if 'effects' in result:
        result['effects'] = [compact_effect(source) for source in result['effects']]
    if 'combat' in result:
        result['combat'].pop('supported', None)
        if not result['combat'].get('castable'):
            result['combat'].pop('castable', None)
    if result.get('overencumbered') is False:
        result.pop('overencumbered')
    return result


def _summary(value, action):
    result = dict(value)
    if result.get('termination') == result.get('reason'):
        result.pop('termination', None)
    for key in ('encountered_blockers', 'warnings', 'stalled_attempts', 'events'):
        if result.get(key) in ([], 0, None):
            result.pop(key, None)
    if not action.get('motion') and not action.get('steps'):
        result.pop('horizontal_displacement_m', None)
    return result


def _event_is_visible(event, observation):
    if event.get('kind') == 'game_message':
        return any(row.get('text') == event.get('text') for row in observation.get('messages', []))
    if event.get('kind') == 'ui_text_added':
        ui = observation.get('ui', {})
        text = ui.get('dialogue', {}).get('text', ui.get('text', ''))
        return bool(event.get('text')) and event['text'] in text
    return any(all(row.get(key) == value for key, value in event.items())
               for row in observation.get('events', []))


def compact_action(result, request_id=None, *, nested=False):
    """One outcome summary and one navigation diagnostic, including child steps."""
    result = deepcopy(result)
    action = result.get('action')
    if not isinstance(action, dict):
        return result
    feedback = result.get('feedback', {})
    summary = result.get('summary')
    if summary is None and feedback.get('status'):
        summarize(result, action.get('operation'))
        summary = result['summary']
    observation = result.get('observation', {})
    if isinstance(summary, dict):
        summary = result['summary'] = _summary(summary, action)
        events = list(summary.get('events', []))
        for event in feedback.get('events', []):
            if not _event_is_visible(event, observation) and event not in events:
                events.append(event)
        if events:
            summary['events'] = events
        # Unknown future feedback fields remain visible instead of being discarded.
        extra = {key: value for key, value in feedback.items()
                 if key not in {'status', 'reason', 'events', 'navigation'}}
        if extra:
            result['feedback'] = extra
        else:
            result.pop('feedback', None)
        for key in ('reason', 'elapsed', 'completed_actions', 'total_actions', 'stopped_step'):
            if key in summary and action.get(key) == summary[key]:
                action.pop(key, None)
    reason = (summary or {}).get('reason', feedback.get('reason', action.get('reason')))
    navigation = feedback.get('navigation') or action.get('navigation')
    if isinstance(navigation, dict):
        value = compact_navigation(navigation, reason)
        if value:
            action['navigation'] = value
        else:
            action.pop('navigation', None)
        if isinstance(result.get('feedback'), dict):
            result['feedback'].pop('navigation', None)
            if not result['feedback']:
                result.pop('feedback')
    if 'body' in action:
        if isinstance(observation, dict) and ('body' in observation or isinstance(observation.get('observation'), int)):
            action.pop('body')
        else:
            body = compact_body(action['body'], equipment=not nested or reason not in SUCCESS_REASONS)
            if nested and reason in SUCCESS_REASONS:
                body = {key: value for key, value in body.items()
                        if key not in {'on_ground', 'swimming', 'air_state'}}
            if body:
                action['body'] = body
            else:
                action.pop('body')
    if action.get('paused') == observation.get('paused') or nested and action.get('paused') is True:
        action.pop('paused', None)
    if isinstance(action.get('motion'), dict):
        motion = action['motion']
        for key in ('pause_drift_m', 'turned_deg', 'pitch_changed_deg'):
            if motion.get(key) == 0:
                motion.pop(key)
        if motion.get('location_changed') is False:
            motion.pop('location_changed')
    if isinstance(action.get('movement'), dict):
        action['movement'] = compact_action({'action': action['movement']}, nested=True)['action']
    if isinstance(action.get('changes'), dict):
        changes = action['changes']
        if changes.get('location_changed') and observation.get('location'):
            changes.pop('location_changed')
        # Nested steps have no observation. Two absent fields are not an
        # already-reported UI transition (and there may be no ui_to to pop).
        if 'ui_to' in changes and 'ui_mode' in observation and changes['ui_to'] == observation['ui_mode']:
            changes.pop('ui_to')
            changes.pop('ui_from', None)
        if 'gold_change' in changes and any(
            event.get('kind') == 'gold_changed' and event.get('amount') == changes['gold_change']
            for event in (summary or {}).get('events', [])
        ):
            changes.pop('gold_change')
        if not changes:
            action.pop('changes')
    if 'steps' in action:
        raw_steps = action['steps']
        if len(raw_steps) > 8:
            action.update(steps_total=len(raw_steps), steps_has_more=True,
                          details=f'action-result {request_id or "REQUEST_ID"} --section action --page N')
            raw_steps = raw_steps[-8:]
        steps = []
        for step in raw_steps:
            value = compact_action({
                'action': {key: value for key, value in step.items() if key not in {'feedback', 'summary'}},
                **{key: step[key] for key in ('feedback', 'summary') if key in step},
            }, request_id, nested=True)
            steps.append({**value['action'], **{key: value[key] for key in ('summary', 'feedback') if key in value}})
        action['steps'] = steps
    return result
