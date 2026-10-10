from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from .argument_specs import (ACTION_DEFAULTS, TRIGGERS, ACT_SCHEMA, ACT_LIMITS,
                             ACT_BOOLEANS, CHAIN_SCHEMA, CHAIN_STEPS, CHAIN_MOVEMENT, MAP_ARGUMENT_FIELDS,
                             LONG_ACTION_TIMEOUT, ACTION_TIMEOUT_MULTIPLIER)


class BridgeError(Exception):
    def __init__(self, code, **details):
        super().__init__(code)
        self.details = details

    def response(self):
        return {'error': str(self), **self.details}


class LogDecoder:
    """Small ASCII frames avoid the engine logger's 4 KiB message splitting."""
    def __init__(self):
        self.parts = {}

    def feed(self, line):
        try:
            if b'ASTRA_PART ' in line:
                token, index, total, payload = line.split(b'ASTRA_PART ',1)[1].strip().split(b' ',3)
                index,total=int(index),int(total)
                if not 1<=index<=total<=3000 or len(payload)>1400 or len(token)>100:return None
                now=time.monotonic()
                self.parts={k:v for k,v in self.parts.items() if now-v[0]<30}
                if len(self.parts)>8:self.parts.clear()
                _,expected,parts=self.parts.setdefault(token,(now,total,{}))
                if expected!=total:return None
                parts[index]=bytes.fromhex(payload.decode('ascii'))
                if len(parts)!=total:return None
                raw=b''.join(parts[i] for i in range(1,total+1))
                del self.parts[token]
            elif b'ASTRA_BRIDGE ' in line:
                raw=line.split(b'ASTRA_BRIDGE ',1)[1]
            else:return None
            result=json.loads(raw)
            return result if isinstance(result,dict) else None
        except (ValueError,UnicodeError,KeyError):
            return None


def atomic_json(path: Path, value: dict) -> None:
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    if len(raw) > 32768:
        raise BridgeError("command_too_large")
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


# Second projection boundary: no arbitrary tables from Lua reach the client.
SCALARS = {str, int, float, bool, type(None)}
LEAF_KEYS = {
    "state", "paused", "ui_mode", "epoch", "frame", "text_source", "api_revision",
    "ref", "name", "count", "equipped", "selected", "carried_weight", "capacity",
    "current", "maximum", "level", "strength", "intelligence", "willpower", "agility",
    "speed", "endurance", "personality", "luck", "text", "day", "month", "day_of_month",
    "page", "total", "elapsed", "reason", "submitted", "description", "player_name",
    "player_level", "created",
    "heading_deg", "pitch_deg", "horizontal_fov_deg", "location", "supported", "modal", "revision",
    "role", "enabled", "value", "progress_percent", "speaker", "kind", "distance_m", "bearing_deg",
    "in_reach", "sampling_limited", "forward_m", "sideways_m", "moved_m", "turned_deg",
    "pitch_changed_deg", "location_changed", "outcome", "status", "blocked", "released",
    "panel", "pending_trade", "stance", "on_ground", "swimming", "can_move", "weapon",
    "selected_spell", "selected_enchantment", "animation_busy", "casting", "sneaking", "submerged", "recovering",
    "replans", "remaining_m", "vertical_m",
    "cost", "range", "magnitude_min", "magnitude_max", "duration", "area",
    "success_chance", "unavailable_reason", "charge_current", "charge_max", "condition_current", "condition_max",
    "available",
    "reach_m", "ammunition_count", "remaining_seconds", "attempted", "animation_observed", "animation_complete",
    "health_change", "magicka_change", "charge_change", "count_change", "melee_in_reach", "touch_in_reach",
    "settled",
    "operation", "completed_actions", "total_actions",
    "gold", "gold_change", "from_location", "to_location", "ui_from", "ui_to",
    "radius_m", "source", "not_a_full_map", "clear_m", "height_change_m", "direction", "slope",
    "recovery_count", "blocked_by",
    "notice",
    "chosen_text", "chosen_role",
    "slider_position", "slider_max",
    "aim_assistance", "estimated_flight_seconds", "aim_note",
    "requested_m", "travelled_m",
    "damage_taken",
    "resource_observed",
    "sequence", "start_heading_deg", "sparse",
    "goal_distance_m", "goal_height_change_m", "arrival_tolerance_m", "checkpoint_key", "time_played_seconds",
    "pause_drift_m",
    "dead", "pause_backend",
    "movement_backend",
    "loot_ready", "harmful", "health_effect",
    "path_endpoint_gap_m", "target_adjustment_m",
    "melee_margin_m", "touch_margin_m",
    "ammunition_name", "ammunition_change",
    "base", "modifier", "damage", "race", "class", "birth_sign", "bounty", "reputation", "overencumbered",
    "temporary", "permanent", "from_equipment", "affected_attribute", "affected_skill",
    "levitation", "water_walking", "water_breathing", "slow_fall",
    "tool_type", "uses_remaining", "quality",
    "cast_outcome",
    "view_mode",
    "screen_visible",
    "title", "characters", "offset", "next_offset", "eof", "scope", "phase", "standing_point",
    "simulation_seconds", "journal_count", "instance", "waypoint", "waypoints", "progress_m", "stalled_seconds",
    'activation_distance_m', 'actor_kind', 'aimed', 'air_state',
    'can_pan_down', 'can_pan_left', 'can_pan_right', 'can_pan_up',
    'center_bearing_deg', 'closed', 'control', 'controls_enabled',
    'destination', 'details_visible', 'fullscreen', 'game_time_seconds',
    'horizontal_distance_m', 'image_x', 'image_y', 'jumping_enabled',
    'landed', 'limit_reached', 'looking_enabled', 'max_zoom',
    'memory_ref', 'min_zoom', 'movement_mode', 'name_source',
    'peak_rise_m', 'ready', 'started_airborne', 'took_off',
    'vertical_speed_mps', 'view_distance_m', 'zoom',
}
DICT_KEYS = {
    'aerial', 'attributes', 'body', 'castable',
    'changes', 'combat', 'dialogue', 'document',
    'fatigue', 'health', 'magicka', 'map',
    'motion', 'movement', 'navigation', 'observation',
    'orientation', 'resources', 'scene', 'stats',
    'target_lock', 'terrain', 'trajectory', 'ui',
    'weapon_info',
}
LIST_KEYS = {
    'actions', 'attribute_details', 'available', 'effects',
    'elements', 'entries', 'ground_targets', 'items',
    'markers', 'messages', 'objects', 'passages',
    'rays', 'samples', 'saves', 'skills',
    'spells', 'steps', 'topics',
}
ERRORS = {
    'action_timeout', 'action_unavailable', 'airborne_required', 'cancelled',
    'document_not_open', 'flight_requires_fly', 'game_operation_timeout', 'input_failed',
    'input_timeout', 'invalid_arguments', 'invalid_lock_target', 'jump_requires_ground',
    'levitation_required', 'locked_camera', 'map_not_open', 'movement_conflicts_with_target',
    'native_ui_unavailable', 'no_player', 'nothing_selected', 'observation_failed',
    'operation_failed', 'out_of_reach', 'point_not_ground', 'resume_timeout',
    'save_unavailable', 'selection_ambiguous', 'selection_unavailable', 'stale_document_ref',
    'stale_ref', 'stale_save_ref', 'stale_ui_ref', 'swimming_required',
    'swimming_requires_swim', 'target_locked_unlock_first', 'target_not_aimed', 'target_not_visible',
    'target_required', 'ui_control_disabled', 'ui_element_offscreen', 'ui_open',
    'ui_scroll_unavailable', 'unknown_operation', 'unknown_topic', 'unknown_view',
    'use_act', 'view_unavailable',
}


def check_result(value, depth=0):
    if depth > 12:
        raise BridgeError("invalid_bridge_response")
    if type(value) is dict:
        for key, item in value.items():
            if key in LEAF_KEYS and type(item) in SCALARS:
                if type(item) is float and not math.isfinite(item):
                    raise BridgeError("invalid_bridge_response")
            elif key in DICT_KEYS and type(item) is dict:
                check_result(item, depth + 1)
            elif key in LIST_KEYS and type(item) is list:
                for child in item:
                    if key in {"available", "actions"} and isinstance(child, str):
                        continue
                    if not isinstance(child, dict):
                        raise BridgeError("invalid_bridge_response")
                    check_result(child, depth + 1)
            elif key in {'rect','aim_point'} and type(item) is list and len(item)==(4 if key=='rect' else 2):
                for v in item:
                    number(v,-100000,100000)
            else:
                raise BridgeError("invalid_bridge_response")
    else:
        raise BridgeError("invalid_bridge_response")
    return value


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise BridgeError("invalid_arguments")
    return value


AIR_DIRECTIONS = ('none','forward','back','left','right','forward-left','forward-right','back-left','back-right')

def action_timeout(op, args, base):
    """Watchdogs bound stalled requests, not caller-selected action durations."""
    if op in {'record_stop','finish_session','shutdown'}: return max(base,LONG_ACTION_TIMEOUT)
    if op in ACTION_DEFAULTS and isinstance(args, dict):
        seconds = args.get('max_seconds' if op in {'chain','sequence'} else 'seconds', ACTION_DEFAULTS[op])
        number(seconds, .02, math.inf)
        return base + ACTION_TIMEOUT_MULTIPLIER * seconds
    return base


def validate(op: str, args: dict) -> None:
    if type(args) is not dict:
        raise BridgeError("invalid_arguments")
    fields = {
        "ping": set(), "observe": set(), "stop": set(), "saves": set(), "new_game": set(),
        "quit": set(), "save": {"description"}, "load": {"ref"},
        "inspect": {"view", "page", "topic"}, "use_item": {"ref"}, "select_spell": {"ref"}, "select_enchanted":{"ref"},
        "trigger": {"name"},
        "read": {"ref", "offset", "limit"}, "resetNPC": {"reason"},
        "act": set(ACT_SCHEMA['properties']),
        "jump":{"direction","run","seconds"}, "air_move":{"direction","run","seconds"},
        "look":{"heading_deg","pitch_deg"},
        "ui":set(),"map":{'action','dx','dy','factor','fit'},"choose":{"ref"},"focus":{"ref","wait_ready"},"approach":{"ref","reach","run","under_fire","seconds"},"interact":{"ref","approach","run","seconds","under_fire","adjust_viewpoint"},
        "pick":{"x","y","radius","observation"},"target_info":{"ref"},
        "walk":{"x","y","ref","observation","run","under_fire","seconds"},
        "survey":set(),"ground":set(),"mark":set(),"go":{"ref","run","seconds","under_fire"},
        "evade":{"direction","ref","meters","seconds","run","actions"},
        "edit":{"ref","text"},"adjust":{"ref","position"},
        "ui_hover":{"ref"},"ui_scroll":{"steps"},
        "move_local":{"forward_m","sideways_m","under_fire","run","seconds"},"wait_until":{"condition","percent","ui_mode","seconds","bearing_deg","meters","control"},"fov":{"degrees"},
        "fly":{"ref","forward_m","sideways_m","vertical_m","seconds","under_fire"},
        "swim":{"ref","forward_m","sideways_m","vertical_m","seconds","under_fire"},
        "track":{"ref","seconds","attack"},
        "lock":{"ref"},"unlock":set(),
        "strike":{"ref","charge","air"},"cast":{"ref","air"},
        "chain":set(CHAIN_SCHEMA['properties']),
    }
    if op not in fields or args.keys() - fields[op]:
        raise BridgeError("invalid_arguments")
    if op=='map':
        action=args.get('action')
        allowed=MAP_ARGUMENT_FIELDS
        if not isinstance(action,(str,type(None))) or action not in allowed or args.keys()-({'action'}|allowed[action]):
            raise BridgeError('invalid_arguments')
        if action=='pan':
            number(args.get('dx',0),-10,10);number(args.get('dy',0),-10,10)
            if not args.get('dx',0) and not args.get('dy',0):raise BridgeError('invalid_arguments')
        if action=='zoom':
            if ('factor' in args)==('fit' in args):raise BridgeError('invalid_arguments')
            if 'factor' in args:number(args['factor'],.25,4)
            if 'fit' in args and args['fit'] is not True:raise BridgeError('invalid_arguments')
    if op=='pick':
        for key in ('x','y'):number(args.get(key),0,16383)
        number(args.get('radius',0),0,160)
        if type(args.get('observation')) is not int:raise BridgeError('invalid_arguments')
    if op in {'approach','interact','move_local','walk','wait_until'}:
        if 'seconds' in args:number(args['seconds'],.02,math.inf)
    if op=='interact' and 'approach' in args and type(args['approach']) is not bool:raise BridgeError('invalid_arguments')
    if op=='interact' and 'adjust_viewpoint' in args and type(args['adjust_viewpoint']) is not bool:raise BridgeError('invalid_arguments')
    if op=='wait_until':
        if args.get('condition') not in {'fatigue','animation','passage','ui','controls','landed'}:raise BridgeError('invalid_arguments')
        if args.get('control','controls') not in {'controls','looking','jumping'}:raise BridgeError('invalid_arguments')
        if 'control' in args and args.get('condition')!='controls':raise BridgeError('invalid_arguments')
        number(args.get('percent',100),0,100)
        number(args.get('bearing_deg',0),-180,180)
        number(args.get('meters',1),.1,6)
        if args.get('condition')=='ui' and (not isinstance(args.get('ui_mode'),str) or not args['ui_mode']):raise BridgeError('invalid_arguments')
    if op in {'jump','air_move'}:
        if args.get('direction','none' if op=='jump' else None) not in AIR_DIRECTIONS:raise BridgeError('invalid_arguments')
        if 'run' in args and type(args['run']) is not bool:raise BridgeError('invalid_arguments')
        if 'seconds' in args:number(args['seconds'],.02,math.inf)
    if op=='look':
        if not args:raise BridgeError('invalid_arguments')
        if 'heading_deg' in args:number(args['heading_deg'],0,360)
        if 'pitch_deg' in args:number(args['pitch_deg'],-80,80)
    if op=='focus' and 'wait_ready' in args and type(args['wait_ready']) is not bool:raise BridgeError('invalid_arguments')
    if op == "act":
        for key, (lo, hi) in ACT_LIMITS.items():
            if key in args:
                number(args[key], lo, math.inf if hi is None else hi)
        for key in ACT_BOOLEANS:
            if key in args and type(args[key]) is not bool:
                raise BridgeError("invalid_arguments")
        if "trigger" in args and args["trigger"] not in TRIGGERS:
            raise BridgeError("invalid_arguments")
        if args.get('trigger') in {'GameMenu','Rest'}:
            raise BridgeError('use_trigger_game_menu' if args['trigger']=='GameMenu' else 'use_trigger_rest')
    if op == "trigger" and args.get("name") not in TRIGGERS:
        raise BridgeError("invalid_arguments")
    if op == "inspect":
        if args.get("view") not in {"inventory", "stats", "spells", "journal", "conversations", "combat", "effects", "character"}:
            raise BridgeError("invalid_arguments")
        if "page" in args:
            number(args["page"], 0, 100000)
            if type(args["page"]) is not int:
                raise BridgeError("invalid_arguments")
        if 'topic' in args and (not isinstance(args['topic'],str) or len(args['topic'])>200):
            raise BridgeError('invalid_arguments')
    if op in {"load", "use_item", "select_spell", "select_enchanted", "focus", "approach", "interact", "choose", "edit", "adjust", "track", "lock", "ui_hover", "target_info"}:
        if not isinstance(args.get("ref"), str) or len(args["ref"]) > 100:
            raise BridgeError("invalid_arguments")
    if op=='edit' and (not isinstance(args.get('text'),str) or len(args['text'])>1000 or '\x00' in args['text']):
        raise BridgeError('invalid_arguments')
    if op=='adjust':
        number(args.get('position'),0,1000000)
        if type(args['position']) is not int:raise BridgeError('invalid_arguments')
    if op=='ui_scroll':
        number(args.get('steps'),-10,10)
        if type(args['steps']) is not int:raise BridgeError('invalid_arguments')
    if op=='move_local':
        for k,v in args.items():
            if k in {'forward_m','sideways_m'}:number(v,-math.inf,math.inf)
    if op in {'fly','swim'}:
        values=[number(args.get(k,0),-math.inf,math.inf) for k in ('forward_m','sideways_m','vertical_m')]
        if 'ref' in args:
            if any(values) or not isinstance(args['ref'],str) or not 1<=len(args['ref'])<=100:raise BridgeError('invalid_arguments')
        elif not .01<sum(v*v for v in values):raise BridgeError('invalid_arguments')
        if 'seconds' in args:number(args['seconds'],.2,math.inf)
    if 'under_fire' in args and type(args['under_fire']) is not bool:raise BridgeError('invalid_arguments')
    if op=='fov': number(args.get('degrees'),70,115)
    if op=='approach' and args.get('reach','activate') not in {'activate','melee','touch'}:
        raise BridgeError('invalid_arguments')
    if op=='go':
        if not isinstance(args.get('ref'),str) or not args['ref'].startswith(('passage_','waypoint_','walk_','ground_')) or len(args['ref'])>100:raise BridgeError('invalid_arguments')
        number(args.get('seconds',12),.5,math.inf)
    if op=='evade':
        if args.get('direction') not in {'back','left','right'}:raise BridgeError('invalid_arguments')
        if 'ref' in args and (not isinstance(args['ref'],str) or len(args['ref'])>100):raise BridgeError('invalid_arguments')
        number(args.get('meters',2),.25,math.inf);number(args.get('seconds',4),.2,math.inf)
        if 'run' in args and type(args['run']) is not bool:raise BridgeError('invalid_arguments')
        if 'actions' in args:validate('chain',{'actions':args['actions']})
    if op in {'walk','approach','go','interact','move_local'} and 'run' in args and type(args['run']) is not bool:raise BridgeError('invalid_arguments')
    if op=='walk':
        if 'seconds' in args:number(args['seconds'],.5,math.inf)
        if 'ref' in args:
            if any(k in args for k in ('x','y','observation')) or not isinstance(args['ref'],str) or len(args['ref'])>100:raise BridgeError('invalid_arguments')
        else:
            for key in ('x','y','observation'):
                number(args.get(key),0,1000000 if key=='observation' else 16383)
                if type(args[key]) is not int:raise BridgeError('invalid_arguments')
    if op=='track':
        number(args.get('seconds',1),.1,math.inf)
        if 'attack' in args and type(args['attack']) is not bool:raise BridgeError('invalid_arguments')
    if op in {'strike','cast','chain'}:
        if 'ref' in args and (not isinstance(args['ref'],str) or len(args['ref'])>100):raise BridgeError('invalid_arguments')
        if 'air' in args and type(args['air']) is not bool:raise BridgeError('invalid_arguments')
        if args.get('air') and 'ref' in args:raise BridgeError('invalid_arguments')
        if op=='strike':number(args.get('charge',.8),.1,1.5)
    if op=='chain':
        for key in ('max_seconds','stop_health_pct'):
            spec=CHAIN_SCHEMA['properties'][key]
            number(args.get(key,spec['default']),spec['minimum'],spec.get('maximum',math.inf))
        if 'pursue' in args and type(args['pursue']) is not bool:raise BridgeError('invalid_arguments')
        if args.get('pursue') and (args.get('air') or 'movement' in args):raise BridgeError('invalid_arguments')
        if 'movement' in args:
            m=args['movement']
            if not isinstance(m,dict) or m.keys()-CHAIN_MOVEMENT['properties'].keys():raise BridgeError('invalid_arguments')
            if m.get('direction') not in CHAIN_MOVEMENT['properties']['direction']['enum']:raise BridgeError('invalid_arguments')
            spec=CHAIN_MOVEMENT['properties']['meters'];number(m.get('meters',spec['default']),spec['minimum'],math.inf)
            for k in ('run','face_target'):
                if k in m and type(m[k]) is not bool:raise BridgeError('invalid_arguments')
            if m.get('face_target') is False and 'ref' in args:raise BridgeError('invalid_arguments')
        actions=args.get('actions')
        if not isinstance(actions,list) or not len(actions)>=1:raise BridgeError('invalid_arguments')
        for step in actions:
            if not isinstance(step,dict) or step.get('op') not in CHAIN_STEPS:raise BridgeError('invalid_arguments')
            fields=CHAIN_STEPS[step['op']]['properties'].keys()
            if step.keys()-fields or 'spell' in step and 'item' in step:raise BridgeError('invalid_arguments')
            for key in ('charge','seconds'):
                if key in CHAIN_STEPS[step['op']]['properties']:
                    spec=CHAIN_STEPS[step['op']]['properties'][key]
                    number(step.get(key,spec['default']),spec['minimum'],spec.get('maximum',math.inf))
            for key in ('spell','item'):
                if key in step:
                    spec=CHAIN_STEPS[step['op']]['properties'][key]
                    if not isinstance(step[key],str) or not spec['minLength']<=len(step[key])<=spec['maxLength']:raise BridgeError('invalid_arguments')
    if op == 'read':
        for key, default, low, high in (('offset', 0, 0, 100000000), ('limit', 4000, 1, 8000)):
            value = args.get(key, default)
            if type(value) is not int or not low <= value <= high:
                raise BridgeError('invalid_arguments')
        if 'ref' in args and (not isinstance(args['ref'], str) or not args['ref'].startswith('document_') or len(args['ref']) > 100):
            raise BridgeError('invalid_arguments')
    if op == 'resetNPC':
        reason = args.get('reason')
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 300 or '\x00' in reason:
            raise BridgeError('invalid_arguments')
    if op == "save":
        if not isinstance(args.get("description"), str) or not 1 <= len(args["description"].encode()) <= 160:
            raise BridgeError("invalid_arguments")
