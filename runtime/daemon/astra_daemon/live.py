"""An independent wall-clock viewer; it never supplies recording data."""
from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time

from astra_bridge.encoding import Encoder, select
from astra_bridge.protocol import BridgeError

QUALITIES={'720p30':(1280,720,30),'1080p60':(1920,1080,60)}


def live_command(encoder, first, quality, output, audio, *, probe=False):
    width,height,fps=QUALITIES[quality]
    args=encoder.command(first['width'],first['height'],fps,output,audio)
    del args[args.index('-movflags'):]
    args[args.index('-bf')+1]='0'
    args[args.index('-profile:v')+1]='constrained_baseline' if encoder.codec=='h264_vaapi' else 'baseline'
    if encoder.codec=='libx264':
        args[args.index('-preset')+1]='ultrafast'
        args[args.index('-crf')+1]='23'
        args += ['-tune','zerolatency']
    if audio:
        args[args.index('-c:a')+1]='libopus'
        args[args.index('-b:a')+1]='128k'
    filters=(f'vflip,scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2:'
             'in_range=full:out_range=tv:out_color_matrix=bt709,'
             f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1')
    if encoder.codec=='h264_vaapi':
        if encoder.gpu_conversion and (first['width'],first['height'])==(1920,1080):
            filters=f'vflip,hwupload,scale_vaapi=w={width}:h={height}:format=nv12:out_color_matrix=bt709:out_range=tv,setsar=1'
        else:filters+=',format=nv12,hwupload'
    args[args.index('-vf')+1]=filters
    if probe:args+=['-frames:v','4','-t',str(4/fps),'-f','matroska',str(output)]
    else:args+=['-rtsp_transport','tcp','-muxdelay','0','-f','rtsp',str(output)]
    return args


class Live:
    def __init__(self, session, installation: Path, quality='720p30'):
        self.session,self.installation,self.quality=session,installation,quality
        self.process=None;self.relay=None;self.error=None
        self.frames=0;self.dropped=0;self.audio_dropped=0
        self.closed=threading.Event();self.started=None
        self.video_thread=None;self.audio_thread=None
        self.stream_context=None;self.audio_context=None
        self.log=None;self.relay_log=None

    def start(self):
        if self.quality not in QUALITIES:raise BridgeError('invalid_viewer_quality')
        display=self.session.display
        first=display.frame_stream.fresh()
        media=display.media_stream
        self.audio_enabled=bool(display.sound)
        if self.audio_enabled and not media.audio:raise BridgeError('engine_audio_unavailable')
        directory=self.session.runtime
        encoder,attempts=select(first,QUALITIES[self.quality][2],self.audio_enabled,directory,self.session.recording_settings)
        # Recording's successful High/AAC/MP4 probe is not proof that a live
        # Baseline/Opus filter chain works. Probe this exact chain separately.
        candidates=[encoder]
        if encoder.hardware and self.session.recording_settings['mode']=='auto':
            candidates.append(Encoder(encoder.binary,'libx264',encoder.version))
        for candidate in candidates:
            with tempfile.TemporaryDirectory(prefix='live-probe-',dir=directory) as temporary:
                tmp=Path(temporary);audio=tmp/'audio.f32' if self.audio_enabled else None
                if audio:audio.write_bytes(bytes(48000*8))
                result=subprocess.run(live_command(candidate,first,self.quality,tmp/'out.mkv',audio,probe=True),
                                      input=first['bgra']*4,capture_output=True,timeout=15)
                attempts.append({'live':True,'encoder':candidate.codec,'gpu_id':candidate.gpu_id,
                                 'device':candidate.device,'cuda_device_index':candidate.cuda_index,'ok':result.returncode==0,
                                 'error':result.stderr.decode(errors='replace')[-1500:]})
                if result.returncode==0:encoder=candidate;break
        else:raise BridgeError('live_encoder_unavailable',attempts=attempts)
        self.encoder=encoder.info();self.attempts=attempts
        logs=self.session.storage/'logs'
        config=directory/'mediamtx.json'
        # JSON is a YAML subset. Only WebRTC media has a published container port.
        config.write_text(json.dumps({'logLevel':'warn','rtsp':True,'rtspAddress':'127.0.0.1:18554',
            'rtspTransports':['tcp'],'rtmp':False,'hls':False,'srt':False,'moq':False,
            'webrtc':True,'webrtcAddress':'127.0.0.1:18889','webrtcLocalUDPAddress':'',
            'webrtcLocalTCPAddress':':'+os.environ.get('ASTRA_RTC_PORT','18771'),
            'webrtcIPsFromInterfaces':False,'webrtcAdditionalHosts':['127.0.0.1'],
            'paths':{'live':{'source':'publisher'}}}))
        self.relay_log=(logs/'mediamtx.log').open('ab')
        self.relay=subprocess.Popen([str(self.installation/'bin/mediamtx'),str(config)],
                                    stdout=self.relay_log,stderr=subprocess.STDOUT,start_new_session=True)
        import socket
        deadline=time.monotonic()+10
        while True:
            try:
                with socket.create_connection(('127.0.0.1',18554),timeout=.2):break
            except OSError:
                if self.relay.poll() is not None or time.monotonic()>deadline:
                    self.close();raise BridgeError('live_relay_failed')
                time.sleep(.05)
        read=None
        if self.audio_enabled:read,self.audio_write=os.pipe()
        self.log=(logs/'live.ffmpeg.log').open('ab')
        self.process=subprocess.Popen(live_command(encoder,first,self.quality,'rtsp://127.0.0.1:18554/live',f'pipe:{read}' if read is not None else None),
            stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=self.log,pass_fds=(read,) if read is not None else (),start_new_session=True)
        if read is not None:os.close(read)
        self.stream_context=display.frame_stream.active();self.stream_context.__enter__()
        if self.audio_enabled:self.audio_context=media.capture();self.audio_context.__enter__()
        self.started=time.monotonic()
        self.video_thread=threading.Thread(target=self._video,args=(first,),daemon=True)
        self.video_thread.start()
        if self.audio_enabled:
            self.audio_thread=threading.Thread(target=self._audio,daemon=True);self.audio_thread.start()

    def _video(self, latest):
        stream=self.session.display.frame_stream
        fps=QUALITIES[self.quality][2];deadline=time.monotonic()
        previous=latest['sequence']
        try:
            while not self.closed.is_set():
                sequence=stream.sequence
                frame=stream.read(sequence) if sequence else None
                if frame:
                    latest=frame
                    self.dropped+=max(0,sequence-previous-1);previous=sequence
                self.process.stdin.write(latest['bgra']);self.frames+=1
                deadline+=1/fps
                delay=deadline-time.monotonic()
                if delay<-.25:deadline=time.monotonic()
                elif delay>0:self.closed.wait(delay)
        except (OSError,ValueError,BridgeError) as exc:
            if not self.closed.is_set():self.error=str(exc);self.closed.set()
        finally:
            # The producer owns stdin. EOF lets FFmpeg leave its input read when
            # closing live view; SIGTERM alone can leave that read blocked.
            try:self.process.stdin.close()
            except (OSError,ValueError):pass

    def _audio(self):
        media=self.session.display.media_stream
        cursor=media.sequence;pending=bytearray();deadline=time.monotonic();count=960*8
        try:
            with os.fdopen(self.audio_write,'wb',buffering=0) as pipe:
                while not self.closed.is_set():
                    newest=media.sequence
                    if newest-cursor>media.slots:
                        self.audio_dropped+=newest-cursor-media.slots;cursor=newest-media.slots;pending.clear()
                    for sequence in range(cursor+1,newest+1):
                        block=media.read(sequence)
                        if block:pending.extend(block['pcm'])
                        else:self.audio_dropped+=1
                    cursor=newest
                    if not media.active:pending.clear()
                    if len(pending)>48000*8//4:
                        self.audio_dropped+=1;del pending[:-count]
                    data=bytes(pending[:count]);del pending[:count]
                    # Silence belongs only to this wall-clock transport. The
                    # Recorder continues to reject gaps in expected game audio.
                    pipe.write(data+bytes(count-len(data)))
                    deadline+=.02
                    if deadline<time.monotonic()-.25:deadline=time.monotonic()
                    self.closed.wait(max(0,deadline-time.monotonic()))
        except (OSError,ValueError) as exc:
            if not self.closed.is_set():self.error=str(exc);self.closed.set()

    def status(self):
        return {'running':bool(self.process and self.process.poll() is None and not self.closed.is_set()),
                'quality':self.quality,'audio':getattr(self,'audio_enabled',False),'frames':self.frames,'source_frames_skipped':self.dropped,
                'audio_discontinuities':self.audio_dropped,'error':self.error,
                'encoder':getattr(self,'encoder',None),'probe_attempts':getattr(self,'attempts',[])}

    def close(self):
        self.closed.set()
        processes=[p for p in (self.process,self.relay) if p and p.poll() is None]
        # These are disposable streaming processes, not the recording encoder.
        # Signal both together and allow one shared grace period.
        for process in processes:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
        deadline=time.monotonic()+1
        for process in processes:
            try:process.wait(timeout=max(.001,deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait(timeout=2)
        for thread in (self.video_thread,self.audio_thread):
            if thread:thread.join(timeout=3)
        if self.process and self.process.stdin:
            try:self.process.stdin.close()
            except (OSError,ValueError):pass
        if self.audio_context:self.audio_context.__exit__(None,None,None);self.audio_context=None
        if self.stream_context:self.stream_context.__exit__(None,None,None);self.stream_context=None
        if self.log:self.log.close()
        if self.relay_log:self.relay_log.close()
