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
