"""Sections relevant to the requested operation, independently of JSON size."""

SNAPSHOTS = {None, 'observe', 'survey', 'scan', 'load', 'new_game', 'restart'}
NAVIGATION = {'walk', 'go', 'move_local', 'approach', 'track', 'revisit', 'return_to',
              'jump', 'air_move', 'fly', 'swim', 'evade', 'retreat'}
COMBAT = {'strike', 'cast', 'chain', 'track', 'lock', 'evade', 'retreat'}
VIEW = {'look', 'focus', 'fov'}


def context_for(operation, action, arguments, before, observation):
    motion = action.get('motion', {})
    moved = any(motion.get(key) for key in ('forward_m', 'sideways_m', 'vertical_m', 'moved_m'))
    location_changed = (bool(before and before.get('location') != observation.get('location'))
                        or motion.get('location_changed') is True
                        or action.get('changes', {}).get('location_changed') is True
                        or action.get('outcome') == 'location_changed')
    navigation = (operation in NAVIGATION or moved or bool(action.get('movement'))
                  or bool(action.get('navigation'))
                  or operation == 'act' and bool(arguments.get('move') or arguments.get('strafe'))
                  or operation == 'interact' and arguments.get('approach', False))
    if operation == 'act' and arguments.get('trigger') == 'Jump' or operation == 'trigger' and arguments.get('name') == 'Jump':
        navigation = True
    # An old receipt may not contain the original inputs. A measured failed
    # translation still needs escape directions, rather than guessing success.
    reason = (action.get('summary', {}).get('reason') or action.get('feedback', {}).get('reason')
              or action.get('reason'))
    if operation == 'act' and reason in {'no_horizontal_progress', 'no_route_progress', 'blocked'}:
        navigation = True
    turning = operation in VIEW or bool(motion.get('turned_deg') or motion.get('pitch_changed_deg'))
    if operation == 'act' and (arguments.get('yaw') or arguments.get('pitch')):
        turning = True
    snapshot = operation in SNAPSHOTS
    combat = operation in COMBAT or operation == 'act' and arguments.get('attack', False)
    selection = (operation in {'select_spell', 'select_enchanted'}
                 or operation == 'trigger' and arguments.get('name') in {'ToggleSpell', 'ToggleWeapon'}
                 or operation == 'act' and arguments.get('trigger') in {'ToggleSpell', 'ToggleWeapon'})
    recovery = operation in {'use_item', 'rest'}
    if operation == 'sequence':
        for step in action.get('steps', arguments.get('actions', [])):
            child = context_for(step.get('operation', step.get('op', '')), step, step, before, observation)
            navigation = navigation or child['terrain']
            turning = turning or child['orientation']
            combat = combat or child['combat']
            selection = selection or child['selection']
            recovery = recovery or child['effects']
    return {
        'snapshot': snapshot,
        'combat': combat,
        'scene': snapshot or navigation or turning or combat or location_changed,
        'terrain': snapshot or navigation or location_changed,
        'physical': snapshot or navigation or combat,
        'selection': selection,
        'vitals': snapshot or navigation or combat or recovery,
        'equipment': snapshot or combat or selection,
        'effects': snapshot or combat or recovery,
        'orientation': snapshot or navigation or turning or combat or location_changed,
    }
