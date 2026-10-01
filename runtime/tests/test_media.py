import struct
import subprocess
from pathlib import Path

import pytest

from astra_bridge.display import Display
from astra_bridge.media_stream import MediaStream
from astra_bridge.screenshots import save_bgra


def test_screenshot_resize_preserves_orientation_and_coordinate_roundtrip(tmp_path):
    from PIL import Image
    # GL bottom row is blue, upper row red. No full-size PNG is written.
    pixels = bytes([255,0,0,255])*(1920*540)+bytes([0,0,255,255])*(1920*540)
    result = save_bgra(tmp_path/'shot.png',pixels,1920,1080,bottom_up=True)
    image = Image.open(tmp_path/'shot.png')
    assert image.size == (1280,720)
    assert image.getpixel((640,100)) == (255,0,0)
    assert image.getpixel((640,620)) == (0,0,255)
    assert result['render_width'] == 1920
    display = Display(tmp_path,tmp_path,':0',False)
    assert display.native_point(640,360) == (960,540)
    public = display.public_coordinates({'scene':{'objects':[{'rect':[900,450,120,60], 'aim_point':[960,480]}]}})
    assert public['scene']['objects'][0] == {'rect':[600,300,80,40], 'aim_point':[640,320]}
    calls=[];display.window='42';display.run=lambda *args:calls.append(args)
    display.click(640,320)
    assert calls[0] == ('mousemove','--window','42',960,480)


def test_pcm_ring_rejects_torn_or_overwritten_audio(tmp_path):
    media=MediaStream(tmp_path/'media.bin')
    try:
        struct.pack_into('<QQI',media.mapping,128,3,4800,2)
        media.mapping[192:208]=struct.pack('<ffff',.25,-.25,.5,-.5)
        assert media.read(1) is None
        struct.pack_into('<Q',media.mapping,128,2)
        block=media.read(1)
        assert block['start']==4800 and block['samples']==2
        assert struct.unpack('<ffff',block['pcm'])==(.25,-.25,.5,-.5)
        struct.pack_into('<Q',media.mapping,128,258)
        assert media.read(1) is None
    finally: media.close()


def test_engine_sample_clock_freezes_thinking_and_includes_ui(tmp_path):
    import os
    root=Path(__file__).resolve().parents[1]
    binary=tmp_path/'media-test'
    subprocess.run(['c++','-std=c++17','-O2','-I',str(root/'native'),
                    str(root/'tests/media_clock.cpp'),'-o',str(binary)],check=True,capture_output=True)
    media=MediaStream(tmp_path/'media.bin')
    try:
        subprocess.run([str(binary)],env={**os.environ,'ASTRA_MEDIA_STREAM':str(media.path)},check=True)
        assert media.get(64)==0 and media.get(72)==88000
        assert media.samples==88000 and media.get(60,'I')==0
        blocks=[media.read(i) for i in range(1,media.sequence+1)]
        cursor=0
        for b in blocks:
            assert b['start']==cursor
            assert struct.unpack_from('<f',b['pcm'])[0]==cursor
            cursor+=b['samples']
        assert cursor==88000
    finally: media.close()
