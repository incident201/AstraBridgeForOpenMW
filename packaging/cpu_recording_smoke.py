#!/usr/bin/env python3
"""Exercise the real Recorder/FFmpeg with synthetic transport data, without game assets."""
from array import array
import argparse
import json
import math
from pathlib import Path
import struct
import subprocess
import threading
import time
from types import SimpleNamespace

from astra_bridge.frame_stream import FrameStream
from astra_bridge.media_stream import MediaStream
from astra_bridge.recording import Recorder


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();root=args.directory;root.mkdir(parents=True,exist_ok=True)
    video=FrameStream(root/'frames.bin',capacity=320*180*4)
    audio=MediaStream(root/'audio.bin')
    done=threading.Event();active=threading.Event();active.set()
    errors=[]
    def producer():
        samples=sequence=frames=heartbeat=0;recording=False
        try:
            struct.pack_into('<I',audio.mapping,40,1)
            while not done.is_set():
                heartbeat+=1
                requested=bool(audio.get(56,'I'))
                if recording!=requested:
                    recording=requested
                    struct.pack_into('<Q',audio.mapping,64 if recording else 72,samples)
                    struct.pack_into('<I',audio.mapping,60,int(recording))
                struct.pack_into('<Q',audio.mapping,96,heartbeat)
                struct.pack_into('<I',audio.mapping,44,int(active.is_set()))
                start=samples
                if active.is_set():
                    count=1600
                    if recording or audio.get(108,'I'):
                        sequence+=1;offset=128+((sequence-1)%audio.slots)*(64+audio.capacity*8)
                        pcm=array('f',(math.sin((samples+i//2)*2*math.pi*440/48000)*.1 for i in range(count*2))).tobytes()
                        struct.pack_into('<QQI',audio.mapping,offset,sequence*2+1,samples,count)
                        audio.mapping[offset+64:offset+64+len(pcm)]=pcm
                        struct.pack_into('<Q',audio.mapping,offset,sequence*2)
                        struct.pack_into('<Q',audio.mapping,24,sequence)
                    samples+=count;struct.pack_into('<Q',audio.mapping,32,samples)
                struct.pack_into('<Q',video.mapping,32,heartbeat)
                if struct.unpack_from('<I',video.mapping,16)[0]:
                    frames+=1;offset=64+((frames-1)%video.slots)*(64+video.capacity)
                    pixels=bytes((40,80,120+heartbeat%80,255))*(320*180)
                    struct.pack_into('<QdIII',video.mapping,offset,frames*2+1,time.monotonic(),320,180,len(pixels))
                    struct.pack_into('<QQI',video.mapping,offset+32,start,samples,int(active.is_set())|(2 if recording else 0))
                    video.mapping[offset+64:offset+64+len(pixels)]=pixels
                    struct.pack_into('<Q',video.mapping,offset,frames*2);struct.pack_into('<Q',video.mapping,24,frames)
                done.wait(1/30)
        except BaseException as exc:errors.append(exc)
    thread=threading.Thread(target=producer,daemon=True);thread.start()
    recorder=None
    try:
        # A viewer-like subscriber exists before and after the recording.
        with audio.capture():
            deadline=time.monotonic()+5
            while not video.supported and time.monotonic()<deadline:time.sleep(.01)
            display=SimpleNamespace(frame_stream=video,media_stream=audio,sound=True)
            recorder=Recorder(display,root/'cpu.mp4',encoding_options={'mode':'cpu'})
            time.sleep(.35);active.clear();time.sleep(.1)
            before=audio.samples;time.sleep(.25);assert audio.samples==before
            active.set();time.sleep(.35)
            result=recorder.stop();recorder=None
            assert result['error'] is None,result
            assert result['upload_ready'] and result['encoder']=='libx264' and result['frames']>10,result
            assert abs(result['av_difference_ms'])<17,result
            binary=result['ffmpeg_path'];probe=Path(binary).with_name('ffprobe')
            data=json.loads(subprocess.check_output([str(probe),'-v','error','-show_streams','-show_format','-of','json',str(root/'cpu.mp4')],text=True))
            video_stream=next(s for s in data['streams'] if s['codec_type']=='video')
            sound=next(s for s in data['streams'] if s['codec_type']=='audio')
            assert (video_stream['width'],video_stream['height'],video_stream['r_frame_rate'])==(1920,1080,'60/1')
            assert video_stream['codec_name']=='h264' and sound['codec_name']=='aac' and sound['sample_rate']=='48000'
            subprocess.run([binary,'-v','error','-i',str(root/'cpu.mp4'),'-f','null','-'],check=True)
            (root/'verification.json').write_text(json.dumps({'fixture':'synthetic transport producer','recording':result,'ffprobe':data},indent=2)+'\n')
            print(json.dumps({'encoder':result['encoder'],'frames':result['frames'],'av_difference_ms':result['av_difference_ms'],'decoded':True}))
    finally:
        if recorder:recorder.stop()
        done.set();thread.join(timeout=5);video.close();audio.close()
    if errors:raise errors[0]


if __name__=='__main__':main()
