import json
from pathlib import Path
import subprocess

import pytest

from astra_bridge.protocol import BridgeError, atomic_json, check_result, validate, LogDecoder


@pytest.mark.parametrize("payload", [
    {"position": {"x": 1}}, {"stats": {"health": {"current": 10, "internal_id": "secret"}}},
    {"items": [{"name": "Зелье", "recordId": "hidden"}]},
    {"saves": [{"description": "Safe", "content_files": ["Morrowind.esm"]}]},
    {"stats": {"health": {"current": float("nan")}}},
])
def test_hidden_or_invalid_observations_fail_closed(payload):
    with pytest.raises(BridgeError):
        check_result(payload)


def test_player_visible_projection():
    assert check_result({"items": [{"name": "Зелье", "ref": "item_1", "count": 2, "equipped": False}],
                         "stats": {"health": {"current": 20, "maximum": 30}}})


def test_dialogue_content_is_not_limited_to_viewport():
    topic={'ref':'ui_available','text':'Доступная тема','role':'button','enabled':True,'screen_visible':False}
    assert check_result({'ui':{'text':'Уже произнесённый ответ',
        'dialogue':{'text':'Уже произнесённый ответ','topics':[topic]},'elements':[topic]}})
    with pytest.raises(BridgeError):
        check_result({'ui':{'dialogue':{'unselected_responses':['future answer']}}})


@pytest.mark.parametrize('steps',[True,1.5,11,-11,None])
def test_native_wheel_rejects_invalid_steps(steps):
    with pytest.raises(BridgeError):validate('ui_scroll',{'steps':steps})


@pytest.mark.parametrize("op,args", [
    ("eval", {"code": "x"}), ("act", {"position": [0, 0, 0]}),
    ("act", {"seconds": 30}), ("act", {"seconds": float("nan")}),
    ("act", {"move": True}), ("act", {"trigger": "Console"}),
    ("trigger", {"name": "ToggleDebug"}), ("inspect", {"view": "nearby"}),
    ("inspect", {"view": "journal", "page": 0.5}), ("save", {"description": ""}),
    ("edit", {"ref":"ui_example","text":12}),
    ("edit", {"ref":"ui_example","text":"bad\x00value"}),
    ("select_enchanted", {"ref":123}),
    ("strike", {"charge":10}), ("cast", {"air":True,"ref":"visible_x"}),
    ("strike", {"air":"yes"}), ("cast", {"seconds":30}),
    ("chain", {"actions":[]}), ("chain", {"actions":[{"op":"eval"}]}),
    ("chain", {"actions":[{"op":"cast","spell":"A","item":"B"}]}),
    ("chain", {"actions":[{"op":"cast"}],"max_seconds":999}),
    ("chain", {"actions":[{"op":"strike","charge":0}]}),
    ("walk", {"x":1,"y":2}), ("walk", {"x":1.5,"y":2,"observation":3}),
    ("walk", {"ref":"walk_test","x":1}), ("walk", {"x":1,"y":2,"observation":True}),
    ("approach", {"ref":"visible_test","run":1}),
])
def test_disallowed_commands(op, args):
    with pytest.raises(BridgeError):
        validate(op, args)

def test_visible_floor_walk_and_resume():
    validate('walk',{'x':640,'y':500,'observation':42,'run':True})
    validate('walk',{'ref':'walk_test'})


def test_atomic_unicode_transport(tmp_path):
    path = tmp_path / "inbox.json"
    atomic_json(path, {"text": "Привет\n\"мир\"", "id": 1})
    assert json.loads(path.read_text())["text"] == 'Привет\n"мир"'
    atomic_json(path, {"id": 2})
    assert json.loads(path.read_text()) == {"id": 2}
    assert not path.with_suffix(".tmp").exists()


def test_lua_projection_and_action_pause():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["lua", "tests/policy.lua"], cwd=root, check=True, capture_output=True)

def test_persistent_target_lock_and_loss():
    root = Path(__file__).resolve().parents[1]
    result=subprocess.run(['lua','tests/motor.lua'],cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr

def test_private_navigation_and_last_seen_target():
    root = Path(__file__).resolve().parents[1]
    result=subprocess.run(['lua','tests/navigation.lua'],cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr

def test_visibility_budget_in_crowded_city():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['lua','tests/sampling.lua'],cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr

def test_scene_occlusion_and_thin_door():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['lua','tests/scene_visibility.lua'],cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr

def test_closed_loop_combat_phases():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['lua','tests/combat.lua'],cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr

def test_combat_adapter_keeps_stock_casting_pulse():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['lua','tests/combat_adapter.lua'],cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr

def test_ranged_adapter_ammunition_and_depletion():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['lua','tests/combat_adapter.lua','ranged'],cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr

def test_camera_speed_and_exterior_borders():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['lua','tests/turning.lua'],cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_long_unicode_messages_survive_logger_prefixes_and_byte_boundaries():
    value={'text':'Реплика\nс кавычками "и" ссылками '*900,'id':3}
    encoded=json.dumps(value,ensure_ascii=False).encode()
    chunks=[encoded[i:i+700] for i in range(0,len(encoded),700)]
    decoder=LogDecoder()
    for i,part in enumerate(chunks,1):
        line=b'[12:00:00 I] Menu: ASTRA_PART abc:3:1 '+str(i).encode()+b' '+str(len(chunks)).encode()+b' '+part.hex().encode()+b'\n'
        result=decoder.feed(line)
        if i<len(chunks):assert result is None
    assert result==value
    assert not decoder.parts
