"""Describe observed outcomes; submission alone is never promoted to success."""
from .outcomes import no_horizontal_progress

def feedback(op, action, before, after, inputs=None):
    why=action.get('reason')
    if why in {'landed','arrived','within_reach','focused','duration','tracked','completed','use_completed','target_down','maneuver_complete','condition_met','ui_opened'}:
        state='succeeded'
    elif why in {'landing_unstable','airborne','step_limit','wall_time_limit','turn_limit','chain_time_limit','settled_outside_goal','condition_timeout'}:
        state='partial'
    elif why in {'insufficient_magicka','insufficient_charge','no_ammunition','power_already_used',
                 'nothing_selected','item_unavailable','not_a_weapon','silenced','out_of_reach','underwater_ranged_unavailable','ballistic_unreachable','rest_unavailable'}:
        state='rejected'
    elif why in {'jump_not_started','player_down','action_not_started'}:
        state='failed'
    elif why in {'no_horizontal_progress','no_observed_movement','blocked','no_path','path_end_out_of_reach','endpoint_mismatch','height_mismatch','navigation_unavailable','cannot_act','maneuver_blocked','ground_required','shot_path_blocked',
                 'no_route_progress','repeated_positions','repeated_obstruction','target_obstructed','viewpoint_blocked','viewpoint_adjustment_needed','target_not_aimed'}:
        state='blocked'
    elif why in {'entered_water','levitation_active','target_lost','ui_open','ui_input_required','game_paused','player_controls_disabled','cancelled','location_changed','player_hurt','swimming_requires_manual_control','cast_not_confirmed','shot_not_confirmed','weapon_changed','health_low','levitation_ended','water_walking_ended','sequence_time_limit'}:
        state='interrupted'
    else:state='submitted' if action.get('submitted') else 'observed'
    if why=='path_end_out_of_reach' and action.get('motion',{}).get('moved_m',0)>.2:state='partial'
    if action.get('outcome')=='activation_sent':state='submitted'
    movement=action.get('movement')
    if movement and state=='succeeded' and movement.get('reason') not in {'maneuver_complete','target_down','following_finished'}:
        state='partial'
    inputs=inputs or {}
    aerial=action.get('aerial',{})
    if op in {'act','trigger'} and action.get('reason')=='duration' and aerial and not aerial.get('took_off'):
        state='failed';why='jump_not_started'
    events=[]
    if aerial.get('damage_taken'):events.append({'kind':'player_damaged','amount':aerial['damage_taken']})
    if action.get('damage_taken') and not aerial.get('damage_taken'):events.append({'kind':'player_damaged','amount':action['damage_taken']})
    changes=action.get('changes',{})
    if 'gold_change' in changes:events.append({'kind':'gold_changed','amount':changes['gold_change']})
    if changes.get('location_changed'):events.append({'kind':'location_changed','name':after.get('location')})
    if changes.get('ui_to'):events.append({'kind':'menu_changed','name':changes['ui_to']})
    if action.get('outcome') in {'dialogue_opened','container_opened','document_opened','item_taken','taken','location_changed','door_opening','door_closing','door_opened','door_closed'}:
        state='succeeded';events.append({'kind':'item_taken' if action['outcome']=='taken' else action['outcome']})
    old_ui=(before or {}).get('ui',{})
    new_ui=after.get('ui',{})
    old_selection=[e['text'] for e in old_ui.get('elements',[]) if e.get('role')=='list_item' and e.get('selected')]
    new_selection=[e['text'] for e in new_ui.get('elements',[]) if e.get('role')=='list_item' and e.get('selected')]
    if op=='choose' and new_selection and old_selection!=new_selection:
        events.append({'kind':'list_selection_changed','selected':new_selection})
    old_notices={e.get('notice') for e in old_ui.get('elements',[])}
    for e in new_ui.get('elements',[]):
        if e.get('notice') and e['notice'] not in old_notices:
            events.append({'kind':e['notice'],'text':e['text']})
            if e['notice'] in {'missing_mortar','potion_name_required','ingredients_required'}:state='rejected'
            elif e['notice']=='potion_failed':state='failed'
            elif e['notice']=='potion_created':state='succeeded'
    # ItemView entries marked pending_trade belong to a proposal, not completed ownership.
    old_slots={e['text'] for e in old_ui.get('elements',[]) if e.get('role')=='item_slot'}
    new_slots={e['text'] for e in new_ui.get('elements',[]) if e.get('role')=='item_slot'}
    if old_slots!=new_slots and old_slots and new_slots:
        events.append({'kind':'selection_changed','selected':sorted(new_slots-old_slots)})
    old_messages={(e.get('text'),e.get('frame')) for e in (before or {}).get('messages',[])}
    message_rows=[e for e in after.get('messages',[]) if e.get('text') and (e['text'],e.get('frame')) not in old_messages]
    for e in message_rows:
        if e.get('notice') and not any(v['kind']==e['notice'] for v in events):
            events.append({'kind':e['notice'],'text':e['text']})
            if e['notice'] in {'missing_mortar','potion_name_required','ingredients_required'}:state='rejected'
            elif e['notice']=='potion_failed':state='failed'
            elif e['notice']=='potion_created':state='succeeded'
    messages=[e['text'] for e in message_rows if not e.get('notice')]
    for message in dict.fromkeys(messages):events.append({'kind':'game_message','text':message})
    old_text={e.get('text') for e in old_ui.get('elements',[]) if e.get('role')=='text'}
    added=[e['text'] for e in new_ui.get('elements',[]) if e.get('role')=='text' and e.get('text') and e['text'] not in old_text and e['text'] not in messages and not e.get('notice')]
    if added:events.append({'kind':'ui_text_added','text':'\n'.join(added[-8:])[-2000:]})
    if state=='submitted' and events:state='observed_change'
    if action.get('outcome')=='activation_sent':
        events.append({'kind':'activation_unconfirmed','next_command':'inspect the current UI, messages and target-info before retrying'})
    if op=='edit':
        old_inputs=[e['text'] for e in old_ui.get('elements',[]) if e.get('role')=='input']
        new_inputs=[e['text'] for e in new_ui.get('elements',[]) if e.get('role')=='input']
        if old_inputs!=new_inputs:state='observed_change';events.append({'kind':'input_changed'})
    if op=='adjust':
        old_sliders=[e.get('slider_position') for e in old_ui.get('elements',[]) if e.get('role')=='slider']
        new_sliders=[e.get('slider_position') for e in new_ui.get('elements',[]) if e.get('role')=='slider']
        if old_sliders!=new_sliders:state='observed_change';events.append({'kind':'slider_changed'})
    notices={e['kind'] for e in events}
    failed_cast=action.get('cast_outcome')=='failed' or any(s.get('cast_outcome')=='failed' for s in action.get('steps',[]))
    if 'spell_failed' in notices or failed_cast:
        state='partial' if op=='chain' else 'failed'
        why='spell_failed'
    elif notices & {'lock_failed','trap_failed'}:state='failed';why=next(e['kind'] for e in events if e['kind'] in {'lock_failed','trap_failed'})
    elif 'lock_impossible' in notices:state='rejected';why='lock_impossible'
    elif notices & {'lock_opened','trap_disarmed'}:state='succeeded'
    if state=='succeeded' and no_horizontal_progress(op,action,inputs):
        # A successful activation can coexist with unsuccessful movement. Keep
        # its event, but do not let that side effect certify horizontal progress.
        state='partial' if action.get('outcome') else 'blocked';why='no_horizontal_progress'
    if action.get('reason')=='ui_input_required':
        state='interrupted';why='ui_input_required'
        events.append({'kind':'ui_input_required','next_command':'ui'})
    if (after.get('body') or {}).get('dead') or (before or {}).get('state')=='running' and after.get('state')=='ended':
        state='failed';why='player_down';events.append({'kind':'player_down'})
    return {'status':state,'events':events,'reason':why,
            'navigation':action.get('navigation')} if action.get('navigation') else {'status':state,'events':events,'reason':why}
