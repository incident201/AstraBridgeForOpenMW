from pathlib import Path
import subprocess

import pytest

from astra_bridge.cli import build_parser
from astra_bridge.feedback import feedback
from astra_bridge.observations import compact
from astra_bridge.protocol import AIR_DIRECTIONS, BridgeError, check_result, validate
from astra_bridge.workflows import validate_sequence
from astra_daemon.commands import catalog


def test_aerial_actions_use_real_adapter_and_release_controls():
    result = subprocess.run(['lua', 'tests/combat_adapter.lua', 'aerial'],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('op', ['jump', 'air_move'])
def test_directions_and_finite_budgets(op):
    for direction in AIR_DIRECTIONS:
        validate(op, {'direction': direction, 'run': True, 'seconds': .25})
    for args in ({'direction': 'up'}, {'direction': 'forward', 'seconds': float('inf')},
                 {'direction': 'right', 'seconds': 0}, {'direction': 'left', 'run': 1},
                 {'direction': 'back', 'target': 'hidden'}, {'direction': 'none', 'jump': True}):
        with pytest.raises(BridgeError):
            validate(op, args)
    validate('wait_until', {'condition': 'landed', 'seconds': 8})


def test_cli_catalog_and_sequences_expose_same_controls():
    args = vars(build_parser().parse_args(['jump', 'forward-left', '--run', '--seconds', '0.3']))
    assert args['direction'] == 'forward-left' and args['run'] and args['seconds'] == .3
    assert catalog()['air-move']['operation'] == 'air_move'
    assert 'landed' in next(f['choices'] for f in catalog()['wait-until']['fields'] if f['name'] == 'condition')
    validate_sequence({'actions': [{'op': 'jump', 'direction': 'forward'},
                                  {'op': 'air_move', 'direction': 'right'},
                                  {'op': 'wait_until', 'condition': 'landed'}]})


def test_compact_body_keeps_explicit_airborne_state_and_zero_speed():
    for speed in (-5.2, 0):
        body = {'on_ground': False, 'swimming': False, 'air_state': 'descending', 'vertical_speed_mps': speed}
        check_result({'body': body})
        assert compact({'body': body})['body'] == body
    check_result({'aerial': {'started_airborne': False, 'took_off': True, 'landed': False,
                             'peak_rise_m': 2.1, 'damage_taken': 0}})


def test_airborne_success_requires_observed_outcome():
    assert feedback('jump', {'reason': 'airborne'}, {}, {})['status'] == 'partial'
    assert feedback('jump', {'reason': 'landed'}, {}, {})['status'] == 'succeeded'
    assert feedback('jump', {'reason': 'jump_not_started'}, {}, {})['status'] == 'failed'
    assert feedback('jump', {'reason': 'entered_water'}, {}, {})['status'] == 'interrupted'
    for op in ('act', 'trigger'):
        result = feedback(op, {'reason': 'duration', 'aerial': {'took_off': False}}, {}, {})
        assert result['status'] == 'failed' and result['reason'] == 'jump_not_started'


def test_motion_sampling_preserves_pause_and_rejects_discontinuities():
    script = """package.path='mod/?.lua;'..package.path
local a=require('scripts.astrabridge.airborne')
local V={}; V.__index=V
local function pos(z) return setmetatable({z=z},V) end
function V.__sub(x,y) return pos(x.z-y.z) end
function V:length() return math.abs(self.z) end
a.sample(0,pos(0),'room',70)
a.sample(.1,pos(70),'room',70)
assert(a.state(false,false,false).air_state=='ascending')
for i=1,100 do a.sample(.1,pos(70),'room',70) end
assert(a.state(false,false,false).vertical_speed_mps==10)
a.sample(.2,pos(35),'room',70)
assert(a.state(false,false,false).air_state=='descending')
a.sample(.2,pos(1000),'room',70)
assert(a.state(false,false,false).vertical_speed_mps==nil)
a.sample(.3,pos(5000),'other',70)
assert(a.state(false,false,false).air_state=='airborne')
assert(a.state(true,false,false).vertical_speed_mps==0)
assert(a.state(false,true,false).air_state=='swimming')
assert(a.state(false,false,true).air_state=='levitating')
a.reset(); assert(a.state(false,false,false).vertical_speed_mps==nil)
"""
    result = subprocess.run(['lua', '-'], input=script, cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
