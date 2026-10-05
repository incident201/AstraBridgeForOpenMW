from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from pathlib import Path
import json
import subprocess

import pytest
from PIL import Image

from astra_bridge.cli import build_parser
from astra_bridge.game_map import view_map
from astra_bridge.protocol import BridgeError, check_result, validate
from astra_bridge.screenshots import save_bgra
from astra_bridge.observations import prune_screenshots, present_response
from astra_daemon.commands import catalog


def test_map_catalog_keeps_the_legacy_call_and_explicit_actions():
    parser = build_parser()
    assert parser.parse_args(['map']).action is None
    args = parser.parse_args(['map','zoom','--factor','2'])
    assert args.factor == 2 and args.fit is None
    assert parser.parse_args(['map','zoom','--fit']).fit
    fields = catalog()['map']['fields']
    assert all('default' not in f for f in fields if f['name'] in {'action','dx','dy','factor','fit','query','page','limit'})


@pytest.mark.parametrize('args', [{}, {'action':'local'}, {'action':'world'}, {'action':'view'},
    {'action':'close'}, {'action':'markers'}, {'action':'pan','dx':-.5}, {'action':'pan','dy':1},
    {'action':'zoom','factor':.5}, {'action':'zoom','fit':True}])
def test_map_valid_commands(args):
    validate('map',args)


@pytest.mark.parametrize('args', [{'action':'reveal'}, {'action':[]}, {'action':'pan'},
    {'action':'pan','dx':True}, {'action':'pan','dy':float('nan')}, {'action':'pan','dx':11},
    {'action':'zoom'}, {'action':'zoom','factor':0}, {'action':'zoom','factor':2,'fit':True},
    {'action':'zoom','fit':False}, {'action':'local','factor':2}, {'action':'world','cell':'secret'}])
def test_map_rejects_invalid_or_hidden_controls(args):
    with pytest.raises(BridgeError): validate('map',args)


def test_map_projection_only_exposes_view_and_screen_positions():
    assert check_result({'map':{'view_mode':'local','fullscreen':True,'zoom':1,
        'markers':[{'text':'Known door','image_x':.5,'image_y':.6}]}})
    for hidden in ('world_x','cell_id','record_id','position'):
        with pytest.raises(BridgeError):
            check_result({'map':{'markers':[{'text':'Hidden','image_x':.5,hidden:1}]}})


def test_empty_marker_array_survives_lua_storage_roundtrip_without_metatables():
    root = Path(__file__).resolve().parents[1]
    code = """
package.path = 'mod/?.lua;' .. package.path
package.preload['openmw.vfs'] = function() return {} end
package.preload['openmw.markup'] = function() return {} end
local protocol = require('scripts.astrabridge.protocol')
print(protocol.encode({map={markers={}}}))
"""
    result = subprocess.run(['lua','-e',code],cwd=root,capture_output=True,text=True,check=True)
    assert json.loads(result.stdout) == {'map':{'markers':[]}}


def fixture(tmp_path):
    calls = []
    (tmp_path/'screenshots').mkdir()
    state = {'view_mode':'local','zoom':1,'fullscreen':True,
             'markers':[{'text':f'Door {i}','image_x':.5,'image_y':.5} for i in range(25)]}
    recording = False
    @contextmanager
    def record_ui():
        nonlocal recording
        recording = True
        try: yield
        finally: recording = False
    def command(op,args):
        assert recording; calls.append((op,args))
        return {'map':deepcopy(state)}
    def observe(**kwargs):
        assert recording; calls.append(('observe',kwargs))
        return {'observation':7,'state':'running','ui_mode':'Interface','paused':True}
    def capture(path,*,native_size):
        assert recording and native_size; calls.append(('capture',{})); path.write_bytes(b'frame')
        return {'width':1920,'height':1080,'render_width':1920,'render_height':1080}
    return SimpleNamespace(command=command,observe=observe,record_ui=record_ui,runtime=tmp_path,
        session_id='12345678-test',display=SimpleNamespace(frame_stream=SimpleNamespace(supported=True,capture=capture)),
        memory=SimpleNamespace(data={}),screenshot_keep=8), calls


def test_large_map_is_one_native_frame_recorded_with_ui_and_survives_compaction(tmp_path):
    session,calls = fixture(tmp_path)
    result = view_map(session,{'action':'local'})
    assert calls == [('map',{'action':'local'}),('observe',{'capture':False}),('map',{'action':'view'}),('capture',{})]
    assert result['map']['width'] == 1920 and result['map']['has_more']
    assert len(result['map']['markers']) == 20
    assert 'screenshot' not in result['observation']
    assert present_response(result)['map'] == result['map']


def test_marker_query_does_not_take_a_screenshot_or_change_view(tmp_path):
    session,calls = fixture(tmp_path)
    result = view_map(session,{'action':'markers','query':'Door 2','limit':2,'page':1})
    assert calls == [('map',{'action':'markers'})]
    assert [row['text'] for row in result['map']['markers']] == ['Door 21','Door 22']
    assert result['map']['total'] == 6 and result['map']['has_more']


def test_invalid_paging_has_no_ui_side_effects_and_close_returns_normal_observation(tmp_path):
    session,calls = fixture(tmp_path)
    for args in ({'action':'world','query':'door'}, {'action':'markers','limit':0}):
        with pytest.raises(BridgeError): view_map(session,args)
    assert calls == []
    view_map(session,{'action':'close'})
    assert calls == [('map',{'action':'close'}),('observe',{})]


def test_map_png_keeps_native_resolution_and_normal_screenshot_coordinates(tmp_path):
    pixels = bytes([10,20,30,255]) * (1920*1080)
    small = save_bgra(tmp_path/'normal.png',pixels,1920,1080)
    large = save_bgra(tmp_path/'map.png',pixels,1920,1080,native_size=True)
    assert (small['width'],small['height']) == (1280,720)
    assert (large['width'],large['height']) == (1920,1080)
    assert Image.open(tmp_path/'map.png').getpixel((1919,1079)) == (30,20,10)


def test_map_images_share_the_bounded_screenshot_cache(tmp_path):
    for i in range(12): (tmp_path/f'12345678-{i:06}-map.png').write_bytes(b'frame')
    unrelated = tmp_path/'user-map.png'; unrelated.write_bytes(b'user')
    prune_screenshots(tmp_path,SimpleNamespace(data={}),8)
    assert len(list(tmp_path.glob('12345678-*-map.png'))) == 8 and unrelated.exists()
