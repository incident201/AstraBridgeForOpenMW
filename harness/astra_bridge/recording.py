"""60 fps video and 48 kHz native game audio on one engine sample clock.

Capture drains both rings independently of the encoders. Reasoning pauses
advance neither the mix nor the video timeline. Missing audio is an error,
never a silent gap. Screenshots do not change recording resolution.
"""
from __future__ import annotations
from contextlib import nullcontext

import json
import math
import os
from pathlib import Path
import queue
import statistics
import subprocess
import threading
import time

from .protocol import BridgeError


class ActiveClock:
    def __init__(self, now=time.monotonic):
        self.now = now
        self.sources = set()
        self.accumulated = 0.0
        self.since = None
        self.intervals = []

    def set(self, source, active):
        before = bool(self.sources)
        if active: self.sources.add(source)
        else: self.sources.discard(source)
        after = bool(self.sources)
        if after and not before:
            self.since = self.now()
        elif before and not after:
            end = self.now()
            self.intervals.append((self.since, end, self.accumulated))
            self.accumulated += end - self.since
            self.since = None

    def elapsed(self):
        return self.accumulated + (self.now() - self.since if self.since is not None else 0)

    def project(self, timestamp):
        if self.since is not None and timestamp >= self.since:
            return self.accumulated + timestamp - self.since
        for start, end, elapsed in reversed(self.intervals):
            if timestamp >= end: break
            if timestamp >= start: return elapsed + timestamp - start
        return None


class FramePacer:
    """Choose the nearest complete frame at the centres of uniform output slots."""
    def __init__(self, fps, emit):
        self.fps, self.emit = fps, emit
        self.count = 0
        self.previous = None
        self.last_sequence = None
        self.repeated = 0

    def _emit(self, frame):
        if frame['sequence'] == self.last_sequence: self.repeated += 1
        self.last_sequence = frame['sequence']
        self.emit(frame)
        self.count += 1

    def push(self, timestamp, frame):
        if self.previous:
            t, previous = self.previous
            midpoint = (t+timestamp)/2
            while (self.count+.5)/self.fps <= midpoint:
                # Small render jitter should not turn adjacent 60 Hz frames into
                # a drop/repeat pair. Prefer the next unused frame when it lies
                # within half an output slot; real low-FPS gaps still repeat.
                slot=(self.count+.5)/self.fps
                if (previous['sequence']==self.last_sequence
                    and abs(timestamp-slot)<=.5/self.fps): break
                self._emit(previous)
        self.previous = (timestamp, frame)

    def flush(self, elapsed):
        if self.previous:
            while self.count < round(elapsed*self.fps): self._emit(self.previous[1])
        self.previous = None


class Recorder:
    def __init__(self, display, path: Path, fps=60):
        self.display, self.path, self.fps = display, path, fps
        self.stream = display.frame_stream
        if not self.stream or not self.stream.supported:
            raise BridgeError('engine_frame_unavailable_rebuild_engine')
        self.media = display.media_stream
        if not self.media or not self.media.get(96):
            raise BridgeError('engine_media_unavailable_rebuild_engine')
        if display.sound and not self.media.audio:
            raise BridgeError('engine_audio_unavailable')
        self.has_audio = self.media.audio
        self.audio_samples = 0
        self.audio_queue = queue.Queue(maxsize=256)
        self.condition = threading.Condition()
        self.clock = ActiveClock()  # UI event diagnostics only; engine owns media time.
        self.closing = False
        self.frames = 0
        self.error = None
        self.finalized = False
        self.events = []
        self.started = time.monotonic()
        first = self.stream.fresh()
        self.box = {k:first[k] for k in ('width','height')}
        self.input_frames = 0
        self.ring_dropped = 0
        self.queue_high_water = 0
        self.intervals_ms = []
        self.pacer = FramePacer(fps, self._enqueue)
        self.queue = queue.Queue(maxsize=120)
        import imageio_ffmpeg
        ffmpeg = self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        path.parent.mkdir(parents=True, exist_ok=True)
        audio_read, self.audio_write = os.pipe()
        args = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-n', '-f', 'rawvideo',
                '-pixel_format', 'bgra', '-video_size', f'{self.box["width"]}x{self.box["height"]}',
                '-framerate', str(fps), '-thread_queue_size', '128', '-i', 'pipe:0']
        if self.has_audio:
            args += ['-f', 'f32le', '-ar', '48000', '-ac', '2', '-probesize', '32',
                     '-analyzeduration', '0', '-thread_queue_size', '128', '-i', f'pipe:{audio_read}',
                     '-c:a', 'aac', '-b:a', '384k']
        else: args += ['-an']
        args += ['-vf', 'vflip,scale=in_range=full:out_range=tv:out_color_matrix=bt709,setsar=1', '-c:v', 'libx264',
                '-preset', 'veryfast', '-crf', '18', '-threads', '4', '-pix_fmt', 'yuv420p',
                '-profile:v', 'high', '-level:v', '4.2', '-bf', '2', '-flags', '+cgop',
                '-g', str(fps//2), '-x264-params', 'open-gop=0',
                '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
                '-movflags', '+frag_keyframe+delay_moov+default_base_moof',
                '-use_editlist', '1', '-avoid_negative_ts', 'disabled', str(path)]
        self.log = open(path.with_suffix('.ffmpeg.log'), 'wb')
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.log, pass_fds=(audio_read,))
        os.close(audio_read)
        self.writer = threading.Thread(target=self._encode, daemon=True)
        self.thread = threading.Thread(target=self._capture, daemon=True)
        self.stream_context = self.stream.active()
        self.stream_context.__enter__()
        self.frame_cursor = self.stream.sequence
        self.audio_cursor = self.media.sequence
        try:
            self.base_sample = self.media.recording(True)
        except Exception:
            self.media.request_recording(False)
            self.stream_context.__exit__(None,None,None)
            os.close(self.audio_write)
            self.process.stdin.close()
            self.process.kill(); self.process.wait(); self.log.close()
            raise
        self.end_sample = None
        self.audio_writer = threading.Thread(target=self._encode_audio, daemon=True)
        self.writer.start()
        self.audio_writer.start()
        self.thread.start()

    def set_active(self, source, active):
        with self.condition:
            if self.closing: return
            if (source in self.clock.sources) != active:
                self.clock.set(source, active)
                self.events.append({'source': source, 'active': active,
                                    'wall_seconds': round(time.monotonic()-self.started, 6),
                                    'video_seconds': round((self.media.samples-self.base_sample)/48000, 6)})
            self.condition.notify_all()

    def _encode_audio(self):
        try:
            with os.fdopen(self.audio_write, 'wb') as pipe:
                while (block := self.audio_queue.get()) is not None:
                    if self.has_audio: pipe.write(block)
        except Exception:
            self.error = self.error or 'audio_encoder_failed'

    def _audio(self):
        newest = self.media.sequence
        if newest-self.audio_cursor > self.media.slots:
            raise BridgeError('audio_ring_overrun')
        for sequence in range(self.audio_cursor+1, newest+1):
            block = self.media.read(sequence)
            if block is None: raise BridgeError('audio_ring_overrun')
            if block['start'] != self.base_sample+self.audio_samples:
                raise BridgeError('audio_sample_gap')
            try: self.audio_queue.put(block['pcm'], timeout=.25)
            except queue.Full: raise BridgeError('audio_encoder_too_slow') from None
            self.audio_samples += block['samples']
            self.audio_cursor = sequence

    def _enqueue(self, frame):
        if self.error: raise BridgeError(self.error)
        try: self.queue.put(frame['bgra'], timeout=.25)
        except queue.Full: raise BridgeError('video_encoder_too_slow') from None
        self.queue_high_water = max(self.queue_high_water, self.queue.qsize())

    def _capture(self):
        previous_timestamp = None
        cursor = self.frame_cursor
        try:
            with nullcontext():
                while True:
                    if self.error: raise BridgeError(self.error)
                    if self.stream.error: raise BridgeError('video_window_too_large')
                    self._audio()
                    newest = self.stream.sequence
                    first = max(cursor+1, newest-self.stream.slots+1)
                    self.ring_dropped += max(0, first-cursor-1)
                    for sequence in range(first, newest+1):
                        frame = self.stream.read(sequence)
                        cursor = sequence
                        if frame is None:
                            self.ring_dropped += 1
                            continue
                        if any(frame[k] != self.box[k] for k in ('width','height')):
                            raise BridgeError('video_window_resized')
                        active = frame['media_flags'] & 3 == 3 and frame['sample_end'] > self.base_sample
                        t = ((frame['sample_start']+frame['sample_end'])/2-self.base_sample)/48000
                        if active:
                            self.input_frames += 1
                            if previous_timestamp is not None:
                                self.intervals_ms.append((frame['timestamp']-previous_timestamp)*1000)
                            previous_timestamp = frame['timestamp']
                            self.pacer.push(t, frame)
                        else:
                            previous_timestamp = None
                    with self.condition:
                        if self.closing:
                            self._audio()
                            samples = (self.end_sample or self.base_sample)-self.base_sample
                            if self.audio_samples != samples: raise BridgeError('audio_final_sample_gap')
                            output_frames = math.ceil(samples*self.fps/48000)
                            self.pacer.flush(output_frames/self.fps)
                            padding = round(output_frames*48000/self.fps)-samples
                            if padding: self.audio_queue.put(bytes(padding*8), timeout=.25)
                            break
                        self.condition.wait(.002)
        except Exception as exc:
            self.error = str(exc) if isinstance(exc, BridgeError) else 'video_capture_failed'
        finally:
            self.stream_context.__exit__(None,None,None)
            self.closing = True
            if self.error:
                self.media.request_recording(False)
            try: self.audio_queue.put(None, timeout=2)
            except queue.Full: self.error = self.error or 'audio_encoder_stalled'
            # The encoder drains already captured frames before finalizing MP4.
            while self.writer.is_alive():
                try:
                    self.queue.put(None, timeout=.1)
                    break
                except queue.Full: pass

    def _encode(self):
        try:
            while (frame := self.queue.get()) is not None:
                self.process.stdin.write(frame)
                self.frames += 1
        except Exception:
            self.error = self.error or 'video_encoder_failed'
        finally:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=15)
                if self.process.returncode: self.error = self.error or 'video_encoder_failed'
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait()
                self.error = self.error or 'video_encoder_failed'
            self.log.close()

    def status(self):
        with self.condition:
            times = sorted(self.intervals_ms)
            return {'path': str(self.path), 'fps': self.fps, 'frames': self.frames,
                    'duration': round(self.frames/self.fps, 3), 'recording': not self.closing,
                    'capturing': self.media.active, 'audio': self.has_audio, 'error': self.error,
                    'width':self.box['width'], 'height':self.box['height'],
                    'audio_sample_rate':48000 if self.has_audio else None,
                    'audio_samples':self.audio_samples,
                    'audio_duration':round(self.audio_samples/48000,6),
                    'av_difference_ms':round((self.frames/self.fps-self.audio_samples/48000)*1000,3),
                    'audio_backend':'openal_loopback' if self.has_audio else 'disabled',
                    'upload_ready':self.finalized, 'color_space':'bt709',
                    'audio_monitor':bool(self.media.get(104,'I')),
                    'monitor_overflows':self.media.get(80),
                    'capture_backend':self.stream.backend, 'crf':18,
                    'rendered_frames':self.input_frames, 'repeated_frames':self.pacer.repeated,
                    'ring_dropped_frames':self.ring_dropped, 'encoder_queue_peak':self.queue_high_water,
                    'frame_interval_ms': {'median':round(statistics.median(times),3),
                        'p95':round(times[min(len(times)-1, math.floor(len(times)*.95))],3),
                        'max':round(times[-1],3)} if times else None}

    def stop(self):
        try:
            self.end_sample = self.media.recording(False)
        except BridgeError as exc:
            self.error = self.error or str(exc)
            self.end_sample = self.base_sample+self.audio_samples
        # Wait for a completed frame covering the last acknowledged audio block.
        try: self.stream.fresh()
        except BridgeError as exc: self.error = self.error or str(exc)
        with self.condition:
            for source in list(self.clock.sources): self.clock.set(source, False)
            self.closing = True
            self.condition.notify_all()
        self.thread.join(timeout=10)
        self.audio_writer.join(timeout=10)
        self.writer.join(timeout=20)
        if self.thread.is_alive() or self.writer.is_alive() or self.audio_writer.is_alive():
            self.process.kill()
            self.thread.join(timeout=2); self.writer.join(timeout=2)
            self.error = 'video_encoder_timeout'
        if not self.error and self.frames:
            # Keep the recoverable fragmented original until a stream-copy
            # remux completes. No second encoding/generation loss. YouTube
            # recommends front-loaded moov and no edit lists.
            output=self.path.with_suffix('.finalizing.mp4')
            try:
                with self.path.with_suffix('.finalize.log').open('wb') as log:
                    subprocess.run([self.ffmpeg,'-hide_banner','-loglevel','error','-n',
                        '-i',str(self.path),'-map','0','-c','copy','-movflags','+faststart',
                        '-use_editlist','0','-avoid_negative_ts','make_zero',str(output)],
                        stdout=subprocess.DEVNULL,stderr=log,check=True,timeout=540)
                os.replace(output,self.path)
                self.finalized=True
            except (OSError,subprocess.SubprocessError):
                self.error='video_finalization_failed_original_preserved'
                output.unlink(missing_ok=True)
        status = self.status()
        self.path.with_suffix('.json').write_text(json.dumps({**status, 'segments': self.events}, indent=2)+'\n')
        return status
