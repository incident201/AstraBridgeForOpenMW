import json
from pathlib import Path
import subprocess

import pytest
from astra_daemon.replay import RecordingIndex, Replay
from astra_bridge.encoding import Encoder
from astra_bridge.protocol import BridgeError


@pytest.fixture
def fragmented(tmp_path):
    import imageio_ffmpeg
    encoder=Encoder(imageio_ffmpeg.get_ffmpeg_exe(),'libx264')
    output=tmp_path/'movie.mp4'
    command=encoder.command(32,32,60,output)
    result=subprocess.run(command,input=bytes((20,50,90,255))*1024*130,capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr
    return output


def test_complete_fragments_and_b_frame_timestamps(fragmented,tmp_path):
    idx=RecordingIndex(fragmented);idx.scan()
    assert idx.error is None
    assert len(idx.segments)>=4 and idx.fragmented and idx.origin==pytest.approx(0)
    assert idx.end==pytest.approx(130/60)
    assert idx.metadata('x',True)['mime'].startswith('video/mp4; codecs="avc1.')
    out=tmp_path/'subset.mp4';segment=idx.segments[1]
    data=fragmented.read_bytes();out.write_bytes(idx.init+data[segment['offset']:segment['offset']+segment['bytes']])
    import imageio_ffmpeg
    result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(out),'-f','null','-'],capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_partial_payload_is_not_published_and_file_is_unchanged(fragmented,tmp_path):
    complete=RecordingIndex(fragmented);complete.scan();data=fragmented.read_bytes();first=complete.segments[0]
    growing=tmp_path/'growing.mp4';cut=first['offset']+first['bytes']-1;growing.write_bytes(data[:cut])
    idx=RecordingIndex(growing);idx.scan();assert not idx.segments
    with growing.open('ab') as file:file.write(data[cut:])
    idx.scan();assert len(idx.segments)==len(complete.segments)
    assert growing.read_bytes()==data


def test_faststart_replacement_invalidates_old_byte_ranges(fragmented,tmp_path):
    import imageio_ffmpeg
    replay=Replay(tmp_path);info=replay.info(fragmented)
    assert info['ready'];key=info['id'];generation=info['generation']
    assert replay.part(key,generation,'init')
    final=tmp_path/'final.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(fragmented),'-c','copy','-movflags','+faststart',
                    '-use_editlist','0','-avoid_negative_ts','make_zero',str(final)],check=True)
    final.replace(fragmented)
    info=replay.info(None,key)
    assert info['ready'] and info['kind']=='file' and info['generation']!=generation
    assert info['duration']==pytest.approx(130/60,abs=.001)
    with pytest.raises(BridgeError,match='replay_generation_changed'):replay.part(key,generation,'0')
