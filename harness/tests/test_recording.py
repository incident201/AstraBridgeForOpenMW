from astra_bridge.recording import ActiveClock


def test_pauses_do_not_extend_video_and_overlapping_sources_do_not_double_count():
    wall = [0.]
    clock = ActiveClock(lambda: wall[0])
    clock.set('simulation', True)
    wall[0] = 2
    clock.set('simulation', False)
    wall[0] = 102  # model thinks for 100 seconds
    assert clock.elapsed() == 2
    clock.set('ui', True)
    wall[0] = 103
    clock.set('simulation', True)
    wall[0] = 104
    clock.set('ui', False)
    wall[0] = 105
    clock.set('simulation', False)
    wall[0] = 200
    assert clock.elapsed() == 5


def test_paused_camera_motion_is_recorded_without_thinking_time():
    wall=[0.]
    clock=ActiveClock(lambda:wall[0])
    wall[0]=10
    clock.set('camera_motion',True)
    wall[0]=11.5
    clock.set('camera_motion',False)
    wall[0]=100
    assert clock.elapsed()==1.5
    clock.set('simulation',True)
    clock.set('camera_motion',True)
    wall[0]=101
    clock.set('simulation',False)
    clock.set('camera_motion',False)
    assert clock.elapsed()==2.5

from astra_bridge.recording import FramePacer
from astra_bridge.frame_stream import FrameStream
import struct


def test_timestamp_projection_retains_frames_delivered_after_pause():
    wall=[10.];clock=ActiveClock(lambda:wall[0]);clock.set('simulation',True)
    wall[0]=12;clock.set('simulation',False)
    wall[0]=100;clock.set('ui',True)
    assert clock.project(11.9)==1.9000000000000004
    assert clock.project(90) is None
    assert clock.project(101)==3


def test_nearest_frame_pacing_preserves_60_fps_with_jitter():
    frames=[];pacer=FramePacer(60,lambda f:frames.append(f['sequence']))
    for i in range(600):
        pacer.push((i+.5)/60+(.001 if i%2 else -.001),{'sequence':i})
    pacer.flush(10)
    assert frames==list(range(600)) and pacer.repeated==0


def test_slow_source_reports_repeats_and_keeps_duration():
    frames=[];pacer=FramePacer(60,lambda f:frames.append(f['sequence']))
    for i in range(200): pacer.push((i+.5)/20,{'sequence':i})
    pacer.flush(10)
    assert len(frames)==600 and pacer.repeated==400


def test_ring_rejects_in_progress_and_overwritten_frames(tmp_path):
    stream=FrameStream(tmp_path/'frames.bin',capacity=16,slots=2)
    try:
        offset=64
        struct.pack_into('<QdIII',stream.mapping,offset,3,1.,2,2,16)
        stream.mapping[offset+64:offset+80]=b'x'*16
        assert stream.read(1) is None
        struct.pack_into('<Q',stream.mapping,offset,2)
        assert stream.read(1)['bgra']==b'x'*16
        struct.pack_into('<Q',stream.mapping,offset,6)
        assert stream.read(1) is None
        assert stream.read(3)['sequence']==3
        with stream.active():
            with stream.active(): assert struct.unpack_from('<I',stream.mapping,16)[0]==1
            assert struct.unpack_from('<I',stream.mapping,16)[0]==1
        assert struct.unpack_from('<I',stream.mapping,16)[0]==0
    finally: stream.close()
