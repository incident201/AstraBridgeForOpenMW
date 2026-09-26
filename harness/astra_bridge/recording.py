"""30 fps video on a timeline containing active gameplay/UI work only."""
from __future__ import annotations

import json
import os
from pathlib import Path
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

    def set(self, source, active):
        before = bool(self.sources)
        if active:
            self.sources.add(source)
        else:
            self.sources.discard(source)
        after = bool(self.sources)
        if after and not before:
            self.since = self.now()
        elif before and not after:
            self.accumulated += self.now() - self.since
            self.since = None

    def elapsed(self):
        return self.accumulated + (self.now() - self.since if self.since is not None else 0)


class Recorder:
    def __init__(self, display, path: Path, fps=30):
        self.display, self.path, self.fps = display, path, fps
        self.condition = threading.Condition()
        self.clock = ActiveClock()
        self.closing = False
        self.frames = 0
        self.error = None
        self.events = []
        self.started = time.monotonic()
        self.box = display.geometry()
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Fragmented MP4 remains readable even if the controller is interrupted.
        args = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-n', '-f', 'rawvideo',
                '-pixel_format', 'bgra', '-video_size', f'{self.box["width"]}x{self.box["height"]}',
                '-framerate', str(fps), '-i', 'pipe:0', '-an', '-c:v', 'libx264',
                '-preset', 'veryfast', '-crf', '23', '-threads', '2', '-pix_fmt', 'yuv420p',
                '-movflags', '+frag_keyframe+empty_moov+default_base_moof', str(path)]
        self.log = open(path.with_suffix('.ffmpeg.log'), 'wb')
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.log)
        self.thread = threading.Thread(target=self._capture, daemon=True)
        self.thread.start()

    def set_active(self, source, active):
        with self.condition:
            if self.closing:
                return
            if (source in self.clock.sources) != active:
                self.clock.set(source, active)
                self.events.append({'source': source, 'active': active,
                                    'wall_seconds': round(time.monotonic()-self.started, 6),
                                    'video_seconds': round(self.clock.elapsed(), 6)})
            self.condition.notify_all()

    def _capture(self):
        from .window_capture import WindowCapture
        try:
            # XAUTHORITY is configured once by Display.start, shared by all capture threads.
            with WindowCapture(self.display.name,self.display.window) as screen:
                previous = None
                while True:
                    with self.condition:
                        target = round(self.clock.elapsed() * self.fps)
                        if self.frames >= target:
                            if self.closing:
                                break
                            self.condition.wait(1/self.fps if self.clock.sources else .5)
                            continue
                    shot=screen.grab()
                    if shot.width!=self.box['width'] or shot.height!=self.box['height']:
                        self.error='video_window_resized';break
                    current = shot.bgra
                    # Keep real active-time duration if capture/encoding runs below 30 fps.
                    # Reuse the last known image for missed samples; never speed up the game.
                    while self.frames < target:
                        frame = current if self.frames == target-1 or previous is None else previous
                        self.process.stdin.write(frame)
                        self.frames += 1
                    previous = current
        except Exception:
            self.error = 'video_capture_failed'
        finally:
            self.closing = True
            try:
                self.process.stdin.close()
                self.process.wait(timeout=20)
                if self.process.returncode:
                    self.error = self.error or 'video_encoder_failed'
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait()
                self.error = self.error or 'video_encoder_failed'
            self.log.close()

    def status(self):
        with self.condition:
            return {'path': str(self.path), 'fps': self.fps, 'frames': self.frames,
                    'duration': round(self.frames/self.fps, 3), 'recording': not self.closing,
                    'capturing': bool(self.clock.sources), 'audio': False, 'error': self.error,
                    'capture_backend':'xcomposite_window'}

    def stop(self):
        with self.condition:
            for source in list(self.clock.sources):
                self.clock.set(source, False)
            self.closing = True
            self.condition.notify_all()
        self.thread.join(timeout=25)
        if self.thread.is_alive():
            self.process.kill()
            self.thread.join(timeout=3)
            self.error = 'video_encoder_timeout'
        status = self.status()
        try:
            self.path.with_suffix('.json').write_text(json.dumps({**status, 'segments': self.events}, indent=2)+'\n')
        except OSError:
            self.error = 'recording_metadata_write_failed'
            status = self.status()
        return status
