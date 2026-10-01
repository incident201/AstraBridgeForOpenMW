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
