"""Compact results must save context without losing actionable game outcomes."""
import copy
import json
from types import SimpleNamespace

import pytest

from astra_bridge.control import Control
from astra_bridge.information import details, query_ui, receipt_details
from astra_bridge.observations import compact, present_response
from astra_bridge.outcomes import summarize
from astra_bridge.responses import compact_action


def observation(number=1):
    return {
        'observation': number, 'state': 'running', 'paused': True,
        'location': 'Room', 'ui_mode': 'Gameplay', 'screenshot': f'frame-{number}.png',
        'orientation': {'heading_deg': 0, 'pitch_deg': 0, 'horizontal_fov_deg': 100,
                        'view_mode': 'FirstPerson', 'view_distance_m': 102.4},
        'screen': {'width': 1280, 'height': 720, 'render_width': 1920, 'render_height': 1080},
        'stats': {'health': {'current': 100, 'maximum': 100},
                  'fatigue': {'current': 100, 'maximum': 100}, 'gold': 10, 'level': 1},
        'body': {'on_ground': True, 'swimming': False, 'air_state': 'grounded',
                 'vertical_speed_mps': 0, 'controls_enabled': True, 'looking_enabled': True,
                 'jumping_enabled': True, 'can_move': True, 'dead': False,
                 'stance': 'nothing', 'weapon': 'Sword'},
        'target_lock': {'status': 'unlocked'}, 'working_memory': {'available': False},
        'scene': {'objects': [{'ref': 'visible_person', 'kind': 'actor', 'actor_kind': 'npc',
                              'distance_m': 5, 'bearing_deg': 20, 'in_reach': False,
                              'details_visible': False, 'touch_margin_m': -3.2333333,
                              'touch_in_reach': False}], 'sampling_limited': False},
        'terrain': {'passages': [{'ref': 'passage_current', 'direction': 'front', 'bearing_deg': 0,
                                 'distance_m': 6, 'clear_m': 6, 'height_change_m': 0,
                                 'slope': 'level', 'status': 'range_limit'}]},
        'combat': {'supported': True, 'weapon_info': {'name': 'Sword', 'condition_current': 40},
                   'castable': {}},
        'effects': [{'name': 'Resistance', 'temporary': False, 'from_equipment': False,
                     'effects': [{'name': 'Resist Fire', 'magnitude_min': 75, 'magnitude_max': 75,
                                  'permanent': True, 'harmful': False, 'description': 'Long description'}]}],
        'messages': [], 'events': [],
        'exploration': {'segment': 'space_room', 'current_node': 'node_current',
                        'supported': True, 'persistent': True, 'loop_detected': False},
    }


def movement(obs=None, reason='arrived'):
    action = {'reason': reason, 'elapsed': 2, 'paused': True,
              'motion': {'forward_m': 0, 'sideways_m': 0, 'vertical_m': .46,
                         'moved_m': .46, 'turned_deg': 0, 'pause_drift_m': 0, 'location_changed': False},
              'body': observation()['body'],
              'navigation': {'status': reason, 'remaining_m': 0, 'waypoint': 3, 'waypoints': 3,
                             'arrival_tolerance_m': .35714285714286, 'standing_point': False,
                             'replans': 1, 'recovery_count': 0,
                             'motor': {'planner_queries': 20, 'max_update_seconds': .003}}}
    feedback = {'status': 'succeeded', 'reason': reason, 'events': [],
                'navigation': copy.deepcopy(action['navigation'])}
    return summarize({'action': action, 'feedback': feedback,
                      'observation': obs or observation(2)}, 'walk')


def test_repeated_observation_keeps_handles_and_omits_unchanged_bulk():
    old = observation()
    new = observation(2)
    result = compact(new, old)
    for key in ('combat', 'effects', 'screen', 'stats', 'messages', 'events', 'changes',
                'working_memory', 'target_lock'):
        assert key not in result
    assert result['orientation'] == {'heading_deg': 0, 'pitch_deg': 0}
    assert result['body'] == {'on_ground': True, 'swimming': False, 'air_state': 'grounded'}
    assert result['scene']['objects'][0]['ref'] == 'visible_person'
    assert 'touch_margin_m' not in result['scene']['objects'][0]
    assert result['terrain']['passages'] == [{'ref': 'passage_current', 'direction': 'front',
        'distance_m': 6, 'status': 'range_limit'}]
    assert result['exploration'] == {'segment': 'space_room', 'current_node': 'node_current'}
    assert compact(new)['screen'] == {'width': 1280, 'height': 720}


def test_repeated_projection_is_significantly_smaller_without_mutating_receipt():
    raw = movement()
    saved = copy.deepcopy(raw)
    small = present_response(raw, before=observation(), operation='walk')
    assert len(json.dumps(small)) < len(json.dumps(raw)) * .6
    assert raw == saved
    assert present_response(raw, full=True) == saved
    assert small['summary']['destination_reached'] is True
    assert small['summary']['elapsed'] == 2
    assert 'feedback' not in small
    for key in ('reason', 'elapsed', 'body', 'navigation', 'paused'):
        assert key not in small['action']
    assert small['action']['motion']['vertical_m'] == .46
    assert small['summary']['horizontal_displacement_m'] == 0


def test_sequence_location_transition_returns_success_and_preserves_receipt():
    step = movement()
    step['action'].update(operation='move_local', changes={
        'location_changed': True, 'from_location': 'Camp', 'to_location': 'Ashlands'})
    step['action']['motion'].update(forward_m=29.94, moved_m=30.67, vertical_m=-6.65)
    step['summary']['horizontal_displacement_m'] = 29.94
    step['feedback']['events'] = [{'kind': 'location_changed', 'name': 'Ashlands'}]
    raw = {
        'action': {'reason': 'completed', 'completed_actions': 1, 'total_actions': 1,
                   'steps': [{**step['action'], 'feedback': step['feedback'], 'summary': step['summary']}]},
        'summary': {'status': 'succeeded', 'reason': 'completed', 'completed_actions': 1,
                    'total_actions': 1, 'horizontal_displacement_m': 29.94},
        'observation': {**observation(2), 'location': 'Ashlands'},
    }
    saved = copy.deepcopy(raw)
    result = present_response(raw, before=observation(), operation='sequence')
    assert result['summary']['status'] == 'succeeded'
    assert result['summary']['completed_actions'] == 1
    assert result['observation']['location'] == 'Ashlands'
    nested = result['action']['steps'][0]
    assert nested['motion']['forward_m'] == 29.94
    assert nested['changes'] == step['action']['changes']
    assert {'kind': 'location_changed', 'name': 'Ashlands'} in nested['summary']['events']
    assert raw == saved and present_response(raw, full=True) == saved


@pytest.mark.parametrize('changes', [
    {}, {'gold_change': 10}, {'ui_from': 'Dialogue'},
    {'ui_from': 'Gameplay', 'ui_to': 'Dialogue'},
])
def test_nested_changes_without_an_observation_remain_available(changes):
    result = compact_action({'action': {'changes': changes}}, nested=True)
    assert result['action'].get('changes', {}) == changes


@pytest.mark.parametrize('mode,expected', [('Dialogue', {}), ('Gameplay', {'ui_from': 'Gameplay', 'ui_to': 'Dialogue'})])
def test_ui_transition_is_omitted_only_when_observation_reports_it(mode, expected):
    result = compact_action({'action': {'changes': {'ui_from': 'Gameplay', 'ui_to': 'Dialogue'}},
                             'observation': {'ui_mode': mode}})
    assert result['action'].get('changes', {}) == expected


def test_active_navigation_status_without_a_termination_reason():
    raw = {'active_action': {'operation': 'approach', 'navigation': {
        'status': 'planned', 'remaining_m': 10, 'recovery_count': 1}}}
    saved = copy.deepcopy(raw)
    result = present_response(raw, operation='status')
    assert result['active_action']['navigation'] == {
        'status': 'planned', 'remaining_m': 10, 'recovery_count': 1}
    assert raw == saved


@pytest.mark.parametrize('flag', ['controls_enabled', 'looking_enabled', 'jumping_enabled', 'can_move'])
def test_current_control_restrictions_and_their_removal_are_visible(flag):
    old = observation()
    new = observation(2)
    new['body'][flag] = False
    assert compact(new, old)['body'][flag] is False
    assert compact(old, new)['body'][flag] is True
    assert flag not in compact(old, old)['body']


@pytest.mark.parametrize('state', ['ascending', 'descending', 'airborne', 'levitating', 'swimming'])
def test_physical_state_never_depends_on_a_previous_response(state):
    new = observation()
    new['body'].update(air_state=state, on_ground=False, swimming=state == 'swimming',
                       vertical_speed_mps=-2.5, levitation=state == 'levitating')
    result = compact(new, new)['body']
    assert result['air_state'] == state and result['on_ground'] is False
    assert result['vertical_speed_mps'] == -2.5
    if state == 'levitating':
        assert result['levitation'] is True


def test_changed_resources_equipment_and_selected_spell_remain_visible():
    old = observation()
    new = observation(2)
    new['stats']['gold'] += 1
    new['combat']['weapon_info']['condition_current'] -= 1
    new['body']['selected_spell'] = 'Levitate'
    result = compact(new, old)
    assert result['stats'] == {'gold': 11}
    assert result['combat']['weapon_info']['condition_current'] == 39
    assert result['body']['selected_spell'] == 'Levitate'
    removed = copy.deepcopy(new)
    del removed['body']['selected_spell']
    removed['combat']['castable'] = {}
    new['combat']['castable'] = {'name': 'Levitate'}
    result = compact(removed, new)
    assert result['body']['selected_spell'] is None and result['combat']['castable'] == {}


def test_critical_low_resources_remain_explicit_even_when_unchanged():
    new = observation()
    new['stats']['health']['current'] = 10
    new['stats']['fatigue']['current'] = 0
    assert compact(new, new)['stats'] == {'health': {'current': 10, 'maximum': 100},
                                         'fatigue': {'current': 0, 'maximum': 100}}


def test_effect_updates_do_not_repeat_unchanged_permanent_sources_and_ending_is_reported():
    old = observation()
    new = observation(2)
    new['effects'].append({'name': 'Potion', 'temporary': True,
                          'effects': [{'name': 'Levitate', 'remaining_seconds': 3, 'harmful': False}]})
    result = compact(new, old)
    assert [source['name'] for source in result['effects']] == ['Potion']
    assert result['effects'][0]['effects'][0]['remaining_seconds'] == 3
    newer = copy.deepcopy(new)
    newer['effects'][1]['effects'][0]['remaining_seconds'] = 2
    assert compact(newer, new)['effects'][0]['effects'][0]['remaining_seconds'] == 2
    ended = compact(old, new)
    assert 'effects' not in ended
    assert ended['events'] == [{'kind': 'effect_ended', 'name': 'Potion'}]
    old['events'] = [{'kind': 'effect_ended', 'name': 'Potion', 'event_id': 'evidence_1'}]
    assert compact(old, new)['events'] == old['events']


def test_navigation_keeps_blocker_remaining_distance_and_physical_floor_mismatch():
    raw = movement(reason='blocked')
    raw['action']['navigation'].update(blocked_by='geometry', remaining_m=70, goal_height_change_m=4)
    raw['feedback']['navigation'] = copy.deepcopy(raw['action']['navigation'])
    raw = summarize(raw, 'walk')
    result = present_response(raw)
    assert result['summary']['encountered_blockers'] == ['geometry']
    assert result['summary']['destination_reached'] is False
    nav = result['action']['navigation']
    assert nav['blocked_by'] == 'geometry' and nav['remaining_m'] == 70 and nav['goal_height_change_m'] == 4
    assert 'motor' not in nav and 'waypoint' not in nav
    assert 'feedback' not in result


def test_execution_and_game_failure_are_distinct_and_confirmation_events_survive():
    raw = movement(reason='completed')
    raw['feedback'].update(status='failed', reason='spell_failed', events=[{'kind': 'spell_failed'}])
    raw = summarize(raw, 'cast')
    result = present_response(raw)
    assert result['action']['reason'] == 'completed'
    assert result['summary']['status'] == 'failed' and result['summary']['reason'] == 'spell_failed'
    assert result['summary']['events'] == [{'kind': 'spell_failed'}]
    assert result['observation']['scene']['objects'][0].get('touch_margin_m') is None
    assert present_response(raw, operation='cast')['observation']['scene']['objects'][0]['touch_margin_m'] < 0


def test_nested_steps_keep_failures_once_and_do_not_hide_earlier_blockers_at_time_limit():
    step = movement(reason='blocked')
    step['feedback']['navigation']['blocked_by'] = 'actor'
    step = summarize(step, 'go')
    child = {**step['action'], 'operation': 'go', 'feedback': step['feedback'], 'summary': step['summary']}
    raw = summarize({'action': {'reason': 'step_limit', 'elapsed': 20,
                    'steps': [child] + [{'reason': 'arrived', 'body': observation()['body']}] * 10},
                     'feedback': {'status': 'partial', 'reason': 'step_limit'},
                     'observation': observation()}, 'revisit', 0)
    result = present_response(raw, request_id='route-1')
    assert result['summary']['termination'] == 'time_limit'
    assert result['summary']['encountered_blockers'] == ['actor']
    assert result['summary']['stalled_attempts'] == 1
    assert result['action']['steps_total'] == 11 and len(result['action']['steps']) == 8
    assert 'route-1' in result['action']['details']
    assert all('body' not in row for row in result['action']['steps'])
    receipt = {'response': raw, 'request_id': 'route-1'}
    assert receipt_details(receipt, {'section': 'action', 'limit': 1})['response']['data']['steps'][0] == child


def test_messages_and_ui_text_are_not_duplicated_but_required_input_diagnostics_survive():
    new = observation()
    new['messages'] = [{'text': 'Hello', 'frame': 1}]
    new['ui'] = {'modal': True, 'revision': 'popup', 'text': 'Please confirm',
                 'elements': [{'ref': 'ui_ok', 'role': 'button', 'text': 'OK', 'enabled': True}]}
    raw = movement(new, 'ui_input_required')
    raw['feedback'].update(status='interrupted', events=[
        {'kind': 'game_message', 'text': 'Hello'}, {'kind': 'ui_text_added', 'text': 'Please confirm'},
        {'kind': 'ui_input_required', 'next_command': 'ui'}])
    raw = summarize(raw, 'walk')
    result = present_response(raw)
    assert result['summary']['status'] == 'interrupted'
    assert result['summary']['events'] == [{'kind': 'ui_input_required', 'next_command': 'ui'}]
    assert result['observation']['ui']['modal'] and result['observation']['ui']['elements'][0]['ref'] == 'ui_ok'


def test_internals_do_not_advance_comparison_baseline_and_load_resets_it(tmp_path):
    old = observation()
    old.update(ui_mode='Dialogue', ui={'revision': 'a', 'dialogue': {'text': 'First answer'}})
    newer = copy.deepcopy(old)
    newer.update(observation=2, ui={'revision': 'b', 'dialogue': {'text': 'New answer'}})
    s = SimpleNamespace(inbox=tmp_path/'inbox.json', latest_observation=old, uncertain=False)
    c = Control(s)
    current = [old]
    def call(op, args):
        # Internal observations have already read this revision.
        s.latest_observation = current[0]
        return current[0]
    s.call = call
    assert c.execute('observe', {})['ui']['dialogue']['text'] == 'First answer'
    current[0] = newer
    s.latest_observation = newer
    result = c.execute('observe', {})
    assert result['ui']['dialogue']['text'] == 'New answer'
    assert c.execute('observe', {})['ui']['unchanged'] is True
    assert 'combat' in c.execute('load', {'ref': 'save_1'})
    assert 'effects' in c.execute('observe', {'full': True})
    assert 'effects' not in c.execute('observe', {})


def test_explicit_queries_and_full_receipts_keep_requested_data_and_text():
    old = observation()
    raw = movement(old)
    raw['action']['navigation']['motor']['planner_queries'] = 999
    assert present_response(raw, True)['action']['navigation']['motor']['planner_queries'] == 999
    for section in ('body', 'effects', 'combat', 'screen', 'orientation'):
        result = details(SimpleNamespace(latest_observation=old), {'section': section})
        assert present_response(result) == result
    query = {'entries': [{'text': 'Complete journal text. ' * 500}], 'total': 1, 'has_more': False}
    assert present_response(query, operation='inspect') == query
    inventory = {'items': [{'name': 'Sword', 'ref': 'item_sword', 'equipped': False,
                           'description': 'Full tooltip', 'condition_current': 10}]}
    assert present_response(inventory, operation='inspect')['items'] == [
        {'name': 'Sword', 'ref': 'item_sword', 'description': 'Full tooltip', 'condition_current': 10}]
    assert inventory['items'][0]['equipped'] is False


def test_recording_and_character_queries_omit_debug_metadata_with_full_access():
    recording = {'recording': True, 'capturing': False, 'path': 'record.mp4', 'duration': 3,
                 'error': None, 'encoder': 'h264_vaapi', 'hardware_accelerated': True,
                 'ffmpeg_sha256': 'hash', 'frame_interval_ms': {'p95': 100}, 'ring_dropped_frames': 3}
    small = present_response(recording, operation='record_status')
    assert small['path'] == 'record.mp4' and small['recording'] is True and small['capturing'] is False
    assert 'frame_interval_ms' not in small and 'ffmpeg_sha256' not in small
    assert present_response(recording, full=True) == recording
    character = {'player_name': 'Test', 'stats': {'attribute_details': [{'name': 'Strength'}],
        'attributes': {'strength': 40}, 'skills': [{'name': 'Athletics', 'value': 80, 'base': 80}]}}
    assert present_response(character, operation='status')['stats'] == {
        'attributes': {'strength': 40}, 'skills': [{'name': 'Athletics', 'value': 80}]}
    assert present_response(character, operation='inspect', full=True) == character


def test_atlas_keeps_route_selection_data_and_removes_repeated_headers():
    raw = {'supported': True, 'persistent': True, 'not_a_full_map': True, 'sampled_path': True,
           'source': 'travelled_path_and_observed_probes', 'location': 'Room', 'total': 1,
           'segment': 'space_room', 'spaces': [{'ref': 'space_other'}], 'transitions': [{'from': 'node_1'}],
           'nodes': [{'ref': 'node_1', 'location': 'Room', 'distance_m': 1000, 'can_revisit': True,
                      'route_distance_m': 1200, 'revisit_source': 'recorded_trail', 'names': [], 'screenshots': []}]}
    result = present_response(raw, operation='atlas')
    assert 'source' not in result and 'persistent' not in result
    assert 'spaces' not in result and 'transitions' not in result
    assert result['nodes'] == [{'ref': 'node_1', 'distance_m': 1000, 'can_revisit': True,
                               'route_distance_m': 1200, 'revisit_source': 'recorded_trail'}]
    assert present_response(raw, full=True) == raw
    catalog = {'spaces': raw['spaces'], 'transitions': raw['transitions']}
    assert present_response(catalog, operation='atlas') == catalog


def test_explicit_ui_queries_return_requested_text_even_if_already_read():
    old = observation()
    old['ui'] = {'revision': 'dialogue', 'dialogue': {'text': 'An important answer'}}
    query = {'revision': 'dialogue', 'dialogue': {'text': 'An important answer'},
             'elements': [{'ref': 'ui_topic', 'text': 'Topic', 'enabled': True, 'role': 'button'}]}
    small = present_response(query, before=old, operation='ui')
    assert small['dialogue']['text'] == 'An important answer'
    assert small['elements'][0]['ref'] == 'ui_topic'
    assert present_response(query, full=True, before=old, operation='ui') == query
    # An unchanged action revision must not hide a newly visible tooltip/text.
    new = copy.deepcopy(old)
    new.update(ui_mode='Dialogue')
    new['ui']['dialogue']['text'] = 'New tooltip or message'
    assert compact(new, old)['ui']['dialogue']['text'] == 'New tooltip or message'


def test_repeated_ui_only_queries_have_a_delivery_baseline(tmp_path):
    text = 'Important conversation'
    ui = {'revision': 'dialogue', 'dialogue': {'text': text}, 'elements': []}
    session = SimpleNamespace(inbox=tmp_path/'inbox.json', uncertain=False,
                              call=lambda *args: ui)
    control = Control(session)
    assert control.execute('ui', {})['dialogue']['text'] == text
    assert control.execute('ui', {})['dialogue']['text'] == text
    # Filtered rows did not deliver conversation text and must not advance it.
    control.presented_observation = None
    session.call = lambda *args: {'revision': 'dialogue', 'elements': [], 'text_details': 'details ui'}
    control.execute('ui', {'query': 'Topic'})
    session.call = lambda *args: ui
    assert control.execute('ui', {})['dialogue']['text'] == text


def test_combat_condition_updates_do_not_repeat_unchanged_weapon_properties():
    old = observation()
    old['combat']['weapon_info'].update(kind='melee', reach_m=1.8, condition_max=100)
    new = copy.deepcopy(old)
    new['combat']['weapon_info']['condition_current'] = 30
    assert compact(new, old)['combat'] == {'weapon_info': {'condition_current': 30}}
    new['combat']['weapon_info']['name'] = 'New sword'
    assert compact(new, old)['combat']['weapon_info']['name'] == 'New sword'
    irrelevant = copy.deepcopy(old)
    irrelevant['combat']['weapon_info']['aim_assistance'] = {'angle': 20}
    assert 'combat' not in compact(irrelevant, old)


def test_effect_countdown_updates_keep_identity_without_repeating_strength():
    old = observation()
    old['effects'].append({'name': 'Potion', 'temporary': True, 'effects': [
        {'name': 'Fortify Attribute', 'affected_attribute': 'Strength', 'magnitude_min': 20,
         'magnitude_max': 20, 'duration': 30, 'remaining_seconds': 20}]})
    new = copy.deepcopy(old)
    new['effects'][1]['effects'][0]['remaining_seconds'] = 19
    assert compact(new, old)['effects'] == [{'name': 'Potion', 'effects': [
        {'name': 'Fortify Attribute', 'affected_attribute': 'Strength', 'remaining_seconds': 19}]}]
    new['effects'][1]['effects'][0]['magnitude_min'] = 10
    assert compact(new, old)['effects'][0]['effects'][0]['magnitude_min'] == 10


def crowded_observation():
    value = observation(2)
    value['scene']['objects'] = [{
        'ref': f'visible_target_{n}', 'memory_ref': f'object_memory_{n}',
        'kind': 'door' if n % 2 else 'actor', **({'actor_kind': 'npc', 'status': 'active'} if n % 2 == 0 else {}),
        'name': f'Target {n}', 'name_source': 'observed', 'details_visible': True,
        'distance_m': n + 1, 'bearing_deg': n * 5, 'in_reach': n < 2,
    } for n in range(10)]
    return value


@pytest.mark.parametrize('operation', ['look', 'walk', 'go', 'act', 'approach', 'interact',
                                       'choose', 'key', 'revisit', 'sequence', 'wait_until'])
def test_actions_keep_current_target_in_bounded_preview_with_full_expansion(operation):
    current = crowded_observation()
    target = 'visible_target_9'
    raw = movement(current)
    result = present_response(raw, before=observation(), target_ref=target, operation=operation)
    scene = result['observation']['scene']
    assert len(scene['objects']) == 4 and scene['total'] == 10 and scene['has_more']
    assert scene['objects'][0]['ref'] == target
    assert scene['objects'][0]['memory_ref'] == 'object_memory_9'
    assert all('memory_ref' not in row for row in scene['objects'][1:])
    assert result['summary']['destination_reached'] is True
    assert result['observation']['body']['air_state'] == 'grounded'
    assert len(present_response(raw, full=True)['observation']['scene']['objects']) == 10
    expanded = details(SimpleNamespace(latest_observation=current), {'section': 'scene'})
    assert len(expanded['data']['objects']) == 10
    assert expanded['data']['objects'][-1]['memory_ref'] == 'object_memory_9'
    assert raw['observation']['scene'] == current['scene']


def test_explicit_observation_and_combat_keep_wider_scene_and_memory_links():
    current = crowded_observation()
    explicit = present_response(current, operation='observe')
    assert len(explicit['scene']['objects']) == 8
    assert all('memory_ref' in row for row in explicit['scene']['objects'])
    combat = present_response(movement(current), operation='chain', target_ref='visible_target_9')
    assert len(combat['observation']['scene']['objects']) == 8
    assert combat['observation']['scene']['objects'][0]['ref'] == 'visible_target_9'
    assert any(row.get('status') == 'active' for row in combat['observation']['scene']['objects'])


def test_turn_reports_view_and_movement_reports_passages_without_repeating_atlas_node():
    old = observation()
    new = observation(2)
    new['orientation']['heading_deg'] = 90
    new['terrain']['passages'] = [
        {'ref': 'fresh_front', 'direction': 'front', 'bearing_deg': 0, 'distance_m': 6, 'status': 'range_limit'},
        {'ref': 'fresh_back', 'direction': 'back', 'bearing_deg': 180, 'distance_m': 6, 'status': 'range_limit'},
        {'ref': 'fresh_diagonal', 'direction': 'front_left', 'bearing_deg': -30,
         'distance_m': 2, 'clear_m': 2.3, 'height_change_m': 1, 'status': 'nav_boundary'},
    ]
    turn = {'action': {'motion': {'turned_deg': 90}}, 'observation': new}
    turned = present_response(turn, before=old, operation='look')['observation']
    assert turned['orientation']['heading_deg'] == 90 and 'scene' in turned
    assert 'terrain' not in turned
    result = present_response(movement(new), before=old, operation='walk')['observation']
    assert result['orientation']['heading_deg'] == 90
    passages = result['terrain']['passages']
    assert [row['ref'] for row in passages] == ['fresh_front', 'fresh_back', 'fresh_diagonal']
    assert 'bearing_deg' not in passages[0] and 'bearing_deg' not in passages[1]
    assert passages[2]['bearing_deg'] == -30 and passages[2]['clear_m'] == 2.3
    assert 'exploration' not in result
    new['exploration']['current_node'] = 'new_node'
    assert present_response(movement(new), before=old, operation='walk')['observation']['exploration']['current_node'] == 'new_node'
    assert present_response(new, before=old, operation='observe')['exploration']['current_node'] == 'new_node'


@pytest.mark.parametrize('operation', ['use_item', 'select_spell', 'select_enchanted'])
def test_own_state_actions_omit_unrequested_surroundings_but_keep_effects_and_teleports(operation):
    old = observation()
    new = copy.deepcopy(old)
    new['body']['levitation'] = True
    raw = {'action': {'submitted': True}, 'observation': new}
    result = present_response(raw, before=old, operation=operation)['observation']
    assert 'scene' not in result and 'terrain' not in result
    assert result['body']['levitation'] is True
    assert result['screenshot'] == new['screenshot']
    new['scene']['objects'].append({'ref': 'new_object', 'kind': 'door'})
    assert 'scene' not in present_response(raw, before=old, operation=operation)['observation']
    new['scene'] = old['scene']
    new['location'] = 'Another room'
    assert 'scene' in present_response(raw, before=old, operation=operation)['observation']


def test_measured_zero_motion_is_not_repeated_and_unknown_motion_is_not_zero():
    raw = movement()
    raw['action']['motion'].update(vertical_m=0, moved_m=0, turned_deg=90)
    raw['summary']['horizontal_displacement_m'] = 0
    result = present_response(raw, operation='look')
    assert result['action']['motion'] == {'turned_deg': 90}
    assert result['summary']['horizontal_displacement_m'] == 0
    raw['summary']['horizontal_displacement_m'] = None
    assert present_response(raw, operation='look')['action']['motion']['forward_m'] == 0
    assert present_response(raw, operation='look')['summary']['horizontal_displacement_m'] is None


def test_ui_text_is_read_once_and_unrelated_messages_remain_visible():
    new = observation()
    new.update(ui_mode='Dialogue', ui={'dialogue': {'text': 'Greeting.\nTopic\nThe owner will know.'},
        'elements': [{'ref': 'goodbye', 'role': 'button', 'text': 'Goodbye', 'enabled': True}]})
    new['messages'] = [
        {'source': 'ui_text', 'frame': 1, 'text': 'Topic\nThe owner will know.'},
        {'source': 'notification', 'frame': 2, 'text': 'Your journal has been updated.'},
    ]
    result = present_response(movement(new), operation='choose')['observation']
    assert result['ui']['dialogue']['text'] == new['ui']['dialogue']['text']
    assert result['ui']['elements'][0]['ref'] == 'goodbye'
    assert result['messages'] == [{'source': 'notification', 'text': 'Your journal has been updated.'}]
    assert 'scene' not in result and 'terrain' not in result


def test_object_memory_catalog_avoids_per_row_headers_without_losing_names_or_notes():
    raw = {'source': 'observed_object_memory', 'historical': True, 'total': 2, 'objects': [
        {'ref': 'object_one', 'kind': 'item', 'name': 'Cube', 'name_source': 'remembered',
         'source': 'observed_object_memory', 'notes_total': 0},
        {'ref': 'object_two', 'kind': 'actor', 'actor_kind': 'npc',
         'source': 'observed_object_memory', 'notes_total': 2},
    ]}
    result = present_response(raw, operation='knowledge')
    assert result['historical'] is True and result['source'] == raw['source']
    assert result['objects'] == [{'ref': 'object_one', 'kind': 'item', 'name': 'Cube'},
                                 {'ref': 'object_two', 'kind': 'actor', 'actor_kind': 'npc', 'notes_total': 2}]
    assert present_response(raw, full=True, operation='knowledge') == raw


def test_attempt_details_are_removed_only_when_the_summary_covers_their_reasons():
    raw = movement(reason='blocked')
    raw['action']['attempts'] = [{'reason': 'blocked', 'elapsed': 1}, {'reason': 'blocked', 'elapsed': 2}]
    raw['summary']['stalled_attempts'] = 2
    assert 'attempts' not in present_response(raw)['action']
    raw['action']['attempts'][0]['reason'] = 'unexplained_failure'
    assert present_response(raw)['action']['attempts'] == raw['action']['attempts']
    raw['action']['attempts'][0]['reason'] = 'blocked'
    raw['action']['attempts'][0]['custom_diagnostic'] = 'Keep this'
    assert present_response(raw)['action']['attempts'][0]['custom_diagnostic'] == 'Keep this'


def test_finish_session_uses_compact_recording_and_keeps_full_receipt_on_replay(tmp_path, monkeypatch):
    raw = {'closed': True, 'stages': {'save': {'ok': True, 'saved': {'ref': 'save_1'}},
        'recording': {'path': 'record.mp4', 'recording': False, 'upload_ready': True,
                      'ffmpeg_sha256': 'codec_hash', 'frame_interval_ms': {'p95': 20}}}}
    calls = []
    session = SimpleNamespace(inbox=tmp_path/'inbox.json', session_id='session')
    control = Control(session)
    monkeypatch.setattr('astra_bridge.control.finish_session', lambda *args: calls.append(True) or raw)
    try:
        compacted = control.execute('finish_session', {'request_id': 'finish-test'})
        assert compacted['stages']['recording'] == {'path': 'record.mp4', 'recording': False, 'upload_ready': True}
        assert compacted['stages']['save']['saved']['ref'] == 'save_1'
        full = control.execute('action_result', {'ref': 'finish-test', 'full': True})
        assert full['response'] == raw
        replay = control.execute('finish_session', {'request_id': 'finish-test'})
        assert replay['response']['stages']['recording'] == compacted['stages']['recording']
        assert control.execute('finish_session', {'request_id': 'finish-test', 'full': True})['response'] == raw
        assert len(calls) == 1
    finally:
        control.receipts.db.close()


@pytest.mark.parametrize('operation', ['choose', 'edit', 'adjust', 'key', 'click', 'scroll', 'text', 'map', 'trigger'])
def test_ui_operations_do_not_append_unrequested_world_or_character_information(operation):
    old = crowded_observation()
    old.update(ui_mode='Gameplay', ui={'modal': True, 'revision': 'tutorial', 'text': 'Tutorial',
                                      'elements': [{'ref': 'ok', 'role': 'button', 'text': 'OK', 'enabled': True}]})
    new = crowded_observation()
    new['ui'] = {}
    new['stats']['fatigue']['current'] = 90
    new['combat']['weapon_info']['condition_current'] = 30
    raw = {'action': {'submitted': True}, 'observation': new}
    result = present_response(raw, before=old, operation=operation)['observation']
    assert result == {'observation': 2, 'ui_mode': 'Gameplay', 'screenshot': 'frame-2.png'}
    assert present_response(raw, full=True, operation=operation) == raw
    for section in ('stats', 'body', 'terrain', 'scene', 'combat'):
        expanded = details(SimpleNamespace(latest_observation=new), {'section': section})
        assert expanded['data'] == new[section]


def test_consecutive_tutorial_closes_do_not_consume_undelivered_character_updates(tmp_path):
    old = observation()
    old['body']['controls_enabled'] = False
    old['ui'] = {'modal': True, 'revision': 'tutorial', 'text': 'First popup', 'elements': []}
    current = copy.deepcopy(old)
    session = SimpleNamespace(inbox=tmp_path/'inbox.json', uncertain=False, latest_observation=current)
    def call(op, args):
        session.latest_observation = current
        return current if op == 'observe' else {'action': {'submitted': True}, 'observation': current}
    session.call = call
    control = Control(session)
    control.presented_observation = copy.deepcopy(old)
    try:
        for n in range(1, 5):
            current['observation'] = n + 1
            current['stats']['fatigue']['current'] = 90
            current['body']['weapon'] = 'Axe'
            current['combat']['weapon_info'] = {'name': 'Axe', 'condition_current': 20}
            current['effects'] = [{'name': 'Potion', 'temporary': True,
                                   'effects': [{'name': 'Night-Eye', 'remaining_seconds': 20}]}]
            current['ui'] = {'modal': True, 'revision': f'popup-{n}', 'text': f'Popup {n}',
                             'elements': [{'ref': f'ok-{n}', 'role': 'button', 'text': 'OK', 'enabled': True}]}
            result = control.execute('choose', {'ref': f'button-{n}'})['observation']
            assert result['ui']['text'] == f'Popup {n}'
            assert not (result.keys() & {'stats', 'effects', 'combat', 'terrain', 'scene', 'body'})
        current['ui'] = {}
        current['body']['controls_enabled'] = True
        result = control.execute('choose', {'ref': 'last-popup'})['observation']
        assert result['body'] == {'controls_enabled': True}
        assert 'stats' not in result and 'scene' not in result
        requested = control.execute('observe', {})
        assert requested['stats']['fatigue']['current'] == 90
        assert requested['combat']['weapon_info']['name'] == 'Axe'
        assert requested['effects'][0]['name'] == 'Potion'
        assert requested['scene']['objects'] and requested['terrain']['passages']
        current['effects'][0]['effects'][0]['remaining_seconds'] = 19
        assert control.execute('observe', {})['effects'][0]['effects'][0]['remaining_seconds'] == 19
        assert 'effects' not in control.execute('observe', {})
    finally:
        control.receipts.db.close()


def test_requested_movement_combat_and_ui_only_sequences_have_distinct_context():
    old = observation()
    current = copy.deepcopy(old)
    action = {'motion': {'forward_m': 0, 'sideways_m': 0, 'vertical_m': 0, 'moved_m': 0}}
    raw = {'action': action, 'observation': current}
    idle = present_response(raw, before=old, operation='act', arguments={'seconds': 5})
    assert 'terrain' not in idle['observation'] and 'scene' not in idle['observation']
    attempted = present_response(raw, before=old, operation='act', arguments={'move': 1, 'seconds': 5})
    assert attempted['observation']['terrain']['passages']
    fighting = present_response(raw, before=old, operation='act', arguments={'attack': True, 'seconds': 5})
    assert 'scene' in fighting['observation'] and 'terrain' not in fighting['observation']
    for operation, expected in [('choose', False), ('walk', True)]:
        sequence = {'action': {'steps': [{'operation': operation, 'reason': 'completed'}]}, 'observation': current}
        result = present_response(sequence, before=old, operation='sequence')['observation']
        assert ('terrain' in result) is expected
        assert ('scene' in result) is expected


def test_finish_session_recording_failures_are_not_hidden_by_compaction():
    raw = {'closed': False, 'stages': {'recording': {'ok': False, 'reason': 'recording_finalize_failed'}},
           'reason': 'recording_failed_game_kept_open'}
    assert present_response(raw, operation='finish_session') == raw


def test_new_critical_health_is_reported_once_even_during_ui_only_work():
    old = observation()
    new = observation(2)
    new['stats']['health']['current'] = 10
    raw = {'action': {'submitted': True}, 'observation': new}
    assert present_response(raw, before=old, operation='choose')['observation']['stats'] == {
        'health': {'current': 10, 'maximum': 100}}
    assert 'stats' not in present_response(raw, before=new, operation='choose')['observation']


def test_explicit_character_queries_prevent_repeating_already_requested_vitals(tmp_path):
    current = observation()
    session = SimpleNamespace(inbox=tmp_path/'inbox.json', uncertain=False)
    def call(op, args):
        if op == 'inspect':
            return {'stats': current['stats']}
        return current
    session.call = call
    control = Control(session)
    try:
        assert control.execute('inspect', {'view': 'stats'})['stats'] == current['stats']
        assert 'stats' not in control.execute('observe', {})
    finally:
        control.receipts.db.close()


def test_topic_selection_reports_new_answer_not_accumulated_dialogue_history():
    old = observation()
    history = 'An already read greeting and older topic. ' * 100
    old['ui'] = {'revision': 'before-topic', 'dialogue': {'text': history}}
    current = observation(2)
    current.update(ui_mode='Dialogue', ui={
        'revision': 'new-topic', 'dialogue': {'text': history + '\nNew directions\nTurn left at the stairs.'},
        'elements': [{'ref': 'goodbye', 'role': 'button', 'text': 'Goodbye', 'enabled': True}]})
    raw = {'action': {'submitted': True}, 'observation': current}
    result = present_response(raw, before=old, operation='choose')['observation']
    assert result['ui']['dialogue']['text'] == 'New directions\nTurn left at the stairs.'
    assert result['ui']['elements'][0]['ref'] == 'goodbye'
    assert 'text_has_more' not in result['ui']
    assert present_response(raw, full=True)['observation']['ui']['dialogue']['text'] == history + '\nNew directions\nTurn left at the stairs.'
    # Explicit requests still provide the current conversation rather than an empty delta.
    session = SimpleNamespace(command=lambda *args: copy.deepcopy(current['ui']), latest_observation=current)
    queried = query_ui(session, {})
    assert queried['dialogue']['text'].endswith('Turn left at the stairs.')
    assert queried['text_has_more']
    assert details(session, {'section': 'ui'})['data']['dialogue']['text'].startswith(history)


def test_current_ui_mode_is_not_duplicated_in_an_event_but_extra_diagnostics_survive():
    raw = {'action': {'submitted': True}, 'summary': {'status': 'succeeded'},
           'feedback': {'status': 'succeeded', 'events': [
               {'kind': 'menu_changed', 'name': 'Gameplay'},
               {'kind': 'menu_changed', 'name': 'Gameplay', 'custom_detail': 'Keep this'}]},
           'observation': observation()}
    result = present_response(raw, operation='choose')
    assert result['summary']['events'] == [{'kind': 'menu_changed', 'name': 'Gameplay', 'custom_detail': 'Keep this'}]


def test_recent_ui_query_does_not_break_the_next_topic_answer_comparison(tmp_path):
    history = 'An old conversation that has already accumulated. ' * 100
    current = observation()
    current.update(ui_mode='Dialogue', ui={'revision': 'old-topic', 'dialogue': {'text': history}, 'elements': []})
    session = SimpleNamespace(inbox=tmp_path/'inbox.json', uncertain=False,
                              command=lambda *args: copy.deepcopy(current['ui']))
    def call(op, args):
        if op == 'ui':
            return query_ui(session, args)
        return {'action': {'submitted': True}, 'observation': current}
    session.call = call
    control = Control(session)
    try:
        assert len(control.execute('ui', {})['dialogue']['text']) == 1600
        current['ui'] = {'revision': 'new-topic', 'dialogue': {'text': history + '\nThe destination is upstairs.'}}
        result = control.execute('choose', {'ref': 'topic'})
        assert result['observation']['ui']['dialogue']['text'] == 'The destination is upstairs.'
    finally:
        control.receipts.db.close()


def test_delivery_baseline_does_not_repeat_notifications_across_ui_and_world_reads(tmp_path):
    current = observation()
    current['messages'] = [{'source': 'notification', 'frame': 1, 'text': 'Follow me.'}]
    session = SimpleNamespace(inbox=tmp_path/'inbox.json', uncertain=False)
    session.call = lambda op, args: current if op == 'observe' else {'action': {'submitted': True}, 'observation': current}
    control = Control(session)
    try:
        assert control.execute('observe', {})['messages'] == [{'source': 'notification', 'text': 'Follow me.'}]
        assert 'messages' not in control.execute('choose', {'ref': 'ok'})['observation']
        assert 'messages' not in control.execute('observe', {})
        current['messages'].append({'source': 'notification', 'frame': 2, 'text': 'A new warning.'})
        assert control.execute('choose', {'ref': 'next'})['observation']['messages'] == [
            {'source': 'notification', 'text': 'A new warning.'}]
        assert 'messages' not in control.execute('observe', {})
    finally:
        control.receipts.db.close()
