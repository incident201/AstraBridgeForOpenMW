from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path


class BridgeError(Exception):
    pass


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
}
DICT_KEYS = {"stats", "attributes", "health", "magicka", "fatigue", "observation", "orientation", "scene", "ui", "motion", "movement", "target_lock", "body", "navigation", "combat", "weapon_info", "castable", "resources", "changes", "terrain", "trajectory"}
LIST_KEYS = {"items", "spells", "entries", "saves", "available", "objects", "actions", "skills", "topics", "elements", "messages", "effects", "steps", "rays", "passages", "samples", "ground_targets"}
LIST_KEYS.add('attribute_details')
DICT_KEYS.add('dialogue')
ERRORS = {"save_unavailable", "stale_save_ref", "operation_failed", "invalid_arguments", "no_player",
          "game_operation_timeout", "cancelled", "view_unavailable", "unknown_view",
          "ui_open", "use_act", "stale_ref", "action_unavailable", "unknown_operation",
          "action_timeout", "resume_timeout", "observation_failed"}
ERRORS.update({'input_failed','input_timeout'})
ERRORS.update({'native_ui_unavailable','stale_ui_ref','unknown_topic','target_not_visible','out_of_reach','target_not_aimed'})
ERRORS.update({'invalid_lock_target','target_locked_unlock_first','locked_camera'})
ERRORS.update({'nothing_selected','target_required'})
ERRORS.update({'selection_ambiguous','selection_unavailable'})
ERRORS.add('point_not_ground')
ERRORS.add('ui_control_disabled')
ERRORS.update({'ui_element_offscreen', 'ui_scroll_unavailable'})
ERRORS.add('movement_conflicts_with_target')
ERRORS.update({'levitation_required','flight_requires_fly'})


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


TRIGGERS = {"Activate", "ToggleWeapon", "ToggleSpell", "Jump", "Inventory", "Journal", "GameMenu", "Rest"}


def validate(op: str, args: dict) -> None:
    if type(args) is not dict:
        raise BridgeError("invalid_arguments")
    fields = {
        "ping": set(), "observe": set(), "stop": set(), "saves": set(), "new_game": set(),
        "quit": set(), "save": {"description"}, "load": {"ref"},
        "inspect": {"view", "page", "topic"}, "use_item": {"ref"}, "select_spell": {"ref"}, "select_enchanted":{"ref"},
        "trigger": {"name"},
        "act": {"seconds", "move", "strafe", "yaw", "pitch", "attack", "run", "sneak", "trigger", "target"},
        "look":{"heading_deg","pitch_deg"},
        "ui":set(),"map":set(),"choose":{"ref"},"focus":{"ref","wait_ready"},"approach":{"ref","reach","run","under_fire"},
        "walk":{"x","y","ref","observation","run","under_fire"},
        "survey":set(),"ground":set(),"mark":set(),"go":{"ref","run","seconds","under_fire"},
        "evade":{"direction","ref","meters","seconds","run","actions"},
        "edit":{"ref","text"},"adjust":{"ref","position"},
        "ui_hover":{"ref"},"ui_scroll":{"steps"},
        "move_local":{"forward_m","sideways_m","under_fire"},"fov":{"degrees"},
        "fly":{"forward_m","sideways_m","vertical_m","seconds","under_fire"},
        "track":{"ref","seconds","attack"},
        "lock":{"ref"},"unlock":set(),
        "strike":{"ref","charge","air"},"cast":{"ref","air"},
        "chain":{"ref","air","actions","max_seconds","movement","stop_health_pct","pursue"},
    }
    if op not in fields or args.keys() - fields[op]:
        raise BridgeError("invalid_arguments")
    if op=='look':
        if not args:raise BridgeError('invalid_arguments')
        if 'heading_deg' in args:number(args['heading_deg'],0,360)
        if 'pitch_deg' in args:number(args['pitch_deg'],-80,80)
    if op=='focus' and 'wait_ready' in args and type(args['wait_ready']) is not bool:raise BridgeError('invalid_arguments')
    if op == "act":
        for key, lo, hi in [("seconds", .02, 3), ("move", -1, 1), ("strafe", -1, 1),
                            ("yaw", -180, 180), ("pitch", -90, 90)]:
            if key in args:
                number(args[key], lo, hi)
        for key in ("attack", "run", "sneak"):
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
    if op in {"load", "use_item", "select_spell", "select_enchanted", "focus", "approach", "choose", "edit", "adjust", "track", "lock", "ui_hover"}:
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
            if k!='under_fire':number(v,-4,4)
    if op=='fly':
        values=[number(args.get(k,0),-20,20) for k in ('forward_m','sideways_m','vertical_m')]
        if not .01<sum(v*v for v in values)<=400:raise BridgeError('invalid_arguments')
        if 'seconds' in args:number(args['seconds'],.2,15)
    if 'under_fire' in args and type(args['under_fire']) is not bool:raise BridgeError('invalid_arguments')
    if op=='fov': number(args.get('degrees'),70,115)
    if op=='approach' and args.get('reach','activate') not in {'activate','melee','touch'}:
        raise BridgeError('invalid_arguments')
    if op=='go':
        if not isinstance(args.get('ref'),str) or not args['ref'].startswith(('passage_','waypoint_','walk_','ground_')) or len(args['ref'])>100:raise BridgeError('invalid_arguments')
        number(args.get('seconds',12),.5,20)
    if op=='evade':
        if args.get('direction') not in {'back','left','right'}:raise BridgeError('invalid_arguments')
        if 'ref' in args and (not isinstance(args['ref'],str) or len(args['ref'])>100):raise BridgeError('invalid_arguments')
        number(args.get('meters',2),.25,8);number(args.get('seconds',4),.2,8)
        if 'run' in args and type(args['run']) is not bool:raise BridgeError('invalid_arguments')
        if 'actions' in args:validate('chain',{'actions':args['actions']})
    if op in {'walk','approach','go'} and 'run' in args and type(args['run']) is not bool:raise BridgeError('invalid_arguments')
    if op=='walk':
        if 'ref' in args:
            if any(k in args for k in ('x','y','observation')) or not isinstance(args['ref'],str) or len(args['ref'])>100:raise BridgeError('invalid_arguments')
        else:
            for key in ('x','y','observation'):
                number(args.get(key),0,1000000 if key=='observation' else 16383)
                if type(args[key]) is not int:raise BridgeError('invalid_arguments')
    if op=='track':
        number(args.get('seconds',1),.1,3)
        if 'attack' in args and type(args['attack']) is not bool:raise BridgeError('invalid_arguments')
    if op in {'strike','cast','chain'}:
        if 'ref' in args and (not isinstance(args['ref'],str) or len(args['ref'])>100):raise BridgeError('invalid_arguments')
        if 'air' in args and type(args['air']) is not bool:raise BridgeError('invalid_arguments')
        if args.get('air') and 'ref' in args:raise BridgeError('invalid_arguments')
        if op=='strike':number(args.get('charge',.8),.1,1.5)
    if op=='chain':
        number(args.get('max_seconds',12),.5,20)
        number(args.get('stop_health_pct',0),0,100)
        if 'pursue' in args and type(args['pursue']) is not bool:raise BridgeError('invalid_arguments')
        if args.get('pursue') and (args.get('air') or 'movement' in args):raise BridgeError('invalid_arguments')
        if 'movement' in args:
            m=args['movement']
            if not isinstance(m,dict) or m.keys()-{'direction','meters','run','face_target'}:raise BridgeError('invalid_arguments')
            if m.get('direction') not in {'forward','back','left','right'}:raise BridgeError('invalid_arguments')
            number(m.get('meters',2),.25,8)
            for k in ('run','face_target'):
                if k in m and type(m[k]) is not bool:raise BridgeError('invalid_arguments')
            if m.get('face_target') is False and 'ref' in args:raise BridgeError('invalid_arguments')
        actions=args.get('actions')
        if not isinstance(actions,list) or not 1<=len(actions)<=32:raise BridgeError('invalid_arguments')
        for step in actions:
            if not isinstance(step,dict) or step.get('op') not in {'strike','cast','wait'}:raise BridgeError('invalid_arguments')
            fields={'op','charge'} if step['op']=='strike' else {'op','seconds'} if step['op']=='wait' else {'op','spell','item'}
            if step.keys()-fields or 'spell' in step and 'item' in step:raise BridgeError('invalid_arguments')
            if step['op']=='strike':number(step.get('charge',.8),.1,1.5)
            if step['op']=='wait':number(step.get('seconds',.5),.02,3)
            for key in ('spell','item'):
                if key in step and (not isinstance(step[key],str) or not 1<=len(step[key])<=200):raise BridgeError('invalid_arguments')
    if op == "save":
        if not isinstance(args.get("description"), str) or not 1 <= len(args["description"].encode()) <= 160:
            raise BridgeError("invalid_arguments")
