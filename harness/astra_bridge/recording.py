"""60 fps completed-frame video; paused reasoning time is removed.

Capture drains the engine ring independently of the encoder. A timestamp-based
nearest-frame resampler preserves elapsed active time and exposes every repeat,
ring overrun and encoder stall instead of disguising them as nominal FPS.
"""
from __future__ import annotations

import json
import math
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
        self.condition = threading.Condition()
        self.clock = ActiveClock()
        self.closing = False
        self.frames = 0
        self.error = None
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
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        path.parent.mkdir(parents=True, exist_ok=True)
        args = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-n', '-f', 'rawvideo',
                '-pixel_format', 'bgra', '-video_size', f'{self.box["width"]}x{self.box["height"]}',
                '-framerate', str(fps), '-i', 'pipe:0', '-an', '-vf', 'vflip', '-c:v', 'libx264',
                '-preset', 'veryfast', '-crf', '18', '-threads', '4', '-pix_fmt', 'yuv420p',
                '-g', str(fps*2), '-movflags', '+frag_keyframe+empty_moov+default_base_moof', str(path)]
        self.log = open(path.with_suffix('.ffmpeg.log'), 'wb')
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.log)
        self.writer = threading.Thread(target=self._encode, daemon=True)
        self.thread = threading.Thread(target=self._capture, daemon=True)
        self.writer.start()
        self.thread.start()

    def set_active(self, source, active):
        with self.condition:
            if self.closing: return
            if (source in self.clock.sources) != active:
                self.clock.set(source, active)
                self.events.append({'source': source, 'active': active,
                                    'wall_seconds': round(time.monotonic()-self.started, 6),
                                    'video_seconds': round(self.clock.elapsed(), 6)})
            self.condition.notify_all()

    def _enqueue(self, frame):
        if self.error: raise BridgeError(self.error)
        try: self.queue.put(frame['bgra'], timeout=.25)
        except queue.Full: raise BridgeError('video_encoder_too_slow') from None
        self.queue_high_water = max(self.queue_high_water, self.queue.qsize())

    def _capture(self):
        previous_timestamp = None
        cursor = self.stream.sequence
        try:
            with self.stream.active():
                while True:
                    if self.error: raise BridgeError(self.error)
                    if self.stream.error: raise BridgeError('video_window_too_large')
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
                        with self.condition:
                            t = self.clock.project(frame['timestamp'])
                        if t is not None:
                            self.input_frames += 1
                            if previous_timestamp is not None:
                                self.intervals_ms.append((frame['timestamp']-previous_timestamp)*1000)
                            previous_timestamp = frame['timestamp']
                            self.pacer.push(t, frame)
                        else:
                            previous_timestamp = None
                            # Flush only a completed active interval, after its last frame.
                            with self.condition:
                                ended = [elapsed+end-start for start,end,elapsed in self.clock.intervals
                                         if end <= frame['timestamp']]
                            if ended: self.pacer.flush(ended[-1])
                    with self.condition:
                        if self.closing:
                            self.pacer.flush(self.clock.elapsed())
                            break
                        self.condition.wait(.002)
        except Exception as exc:
            self.error = str(exc) if isinstance(exc, BridgeError) else 'video_capture_failed'
        finally:
            self.closing = True
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
                    'capturing': bool(self.clock.sources), 'audio': False, 'error': self.error,
                    'capture_backend':self.stream.backend, 'crf':18,
                    'rendered_frames':self.input_frames, 'repeated_frames':self.pacer.repeated,
                    'ring_dropped_frames':self.ring_dropped, 'encoder_queue_peak':self.queue_high_water,
                    'frame_interval_ms': {'median':round(statistics.median(times),3),
                        'p95':round(times[min(len(times)-1, math.floor(len(times)*.95))],3),
                        'max':round(times[-1],3)} if times else None}

    def stop(self):
        with self.condition:
            for source in list(self.clock.sources): self.clock.set(source, False)
            self.closing = True
            self.condition.notify_all()
        self.thread.join(timeout=10)
        self.writer.join(timeout=20)
        if self.thread.is_alive() or self.writer.is_alive():
            self.process.kill()
            self.thread.join(timeout=2); self.writer.join(timeout=2)
            self.error = 'video_encoder_timeout'
        status = self.status()
        self.path.with_suffix('.json').write_text(json.dumps({**status, 'segments': self.events}, indent=2)+'\n')
        return status
