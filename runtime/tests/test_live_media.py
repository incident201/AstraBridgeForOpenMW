import subprocess

from astra_bridge.encoding import Encoder
from astra_daemon.live import live_command


def test_silent_viewer_probe_encodes_video_without_requiring_audio(tmp_path):
    import imageio_ffmpeg
    encoder=Encoder(imageio_ffmpeg.get_ffmpeg_exe(),'libx264')
    first={'width':32,'height':32,'bgra':bytes((20,50,90,255))*1024}
    output=tmp_path/'silent.mkv'
    command=live_command(encoder,first,'720p30',output,None,probe=True)
    assert '-an' in command and '-c:a' not in command
    result=subprocess.run(command,input=first['bgra']*4,capture_output=True,timeout=15)
    assert result.returncode==0,result.stderr.decode()
    assert output.stat().st_size>100


def test_viewer_stop_closes_producer_pipe_without_forcing_encoder(tmp_path):
    import os
    import sys
    import threading
    from types import SimpleNamespace
    import pytest
    from astra_daemon.live import Live
    if os.name!='posix':pytest.skip('The runtime uses Linux process groups')
    # Like an FFmpeg input read, this consumer ignores SIGTERM and needs EOF.
    process=subprocess.Popen([sys.executable,'-u','-c',
        "import signal,sys; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('ready'); sys.stdin.buffer.read()"],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,start_new_session=True)
    first={'sequence':1,'bgra':b'frame'}
    live=Live(SimpleNamespace(display=SimpleNamespace(frame_stream=SimpleNamespace(sequence=1,read=lambda _:first))),tmp_path)
    live.process=process
    try:
        assert process.stdout.readline()==b'ready\n'
        live.video_thread=threading.Thread(target=live._video,args=(first,));live.video_thread.start()
        live.close()
        assert process.returncode==0,'The producer must send EOF instead of waiting for a forced kill'
        assert not live.video_thread.is_alive()
    finally:
        if process.poll() is None:process.kill();process.wait()
        process.stdout.close()
