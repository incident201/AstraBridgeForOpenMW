"""Private, seqlocked ring of completed engine frames (Linux x86_64).

The producer publishes only after glReadPixels has completed. A reader copies
between two sequence checks, so a wrap cannot produce a torn image. Independent
read cursors let screenshots and video share the stream without stealing frames.
"""
from __future__ import annotations

from contextlib import contextmanager
import mmap
import os
from pathlib import Path
import struct
import threading
import time

from .protocol import BridgeError


class FrameStream:
    backend = 'engine_back_buffer'

    def __init__(self, path: Path, capacity=1920*1080*4, slots=8):
        self.path, self.capacity, self.slots = path, capacity, slots
        self.lock = threading.Lock()
        self.users = 0
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            os.ftruncate(fd, 64 + slots*(64+capacity))
            self.mapping = mmap.mmap(fd, 0)
        finally:
            os.close(fd)
        self.mapping[:64] = struct.pack('<8sIIIIQQ24x', b'ASTRAFR1', capacity, slots, 0, 0, 0, 0)

    def close(self):
        self.mapping.close()
        self.path.unlink(missing_ok=True)

    @property
    def sequence(self):
        return struct.unpack_from('<Q', self.mapping, 24)[0]

    @property
    def error(self):
        return struct.unpack_from('<I', self.mapping, 20)[0]

    @property
    def supported(self):
        return bool(struct.unpack_from('<Q', self.mapping, 32)[0])

    @contextmanager
    def active(self):
        with self.lock:
            self.users += 1
            struct.pack_into('<I', self.mapping, 16, 1)
        try:
            yield self
        finally:
            with self.lock:
                self.users -= 1
                struct.pack_into('<I', self.mapping, 16, int(self.users > 0))

    def read(self, sequence):
        offset = 64 + ((sequence-1) % self.slots)*(64+self.capacity)
        version, timestamp, width, height, size = struct.unpack_from('<QdIII', self.mapping, offset)
        if version != sequence*2: return None
        if not 0 < size <= self.capacity or size != width*height*4:
            raise BridgeError('video_invalid_frame')
        data = self.mapping[offset+64:offset+64+size]
        start, end, flags = struct.unpack_from('<QQI', self.mapping, offset+32)
        if struct.unpack_from('<Q', self.mapping, offset)[0] != version: return None
        return {'sequence': sequence, 'timestamp': timestamp, 'width': width, 'height': height, 'bgra': data,
                'sample_start':start, 'sample_end':end, 'media_flags':flags}

    def fresh(self, timeout=3):
        with self.active():
            before = self.sequence
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self.error:
                    raise BridgeError('video_window_too_large')
                # Two rendered frames after the request also cover a queued draw.
                if self.sequence >= before+2:
                    frame = self.read(self.sequence)
                    if frame: return frame
                time.sleep(.002)
        raise BridgeError('engine_frame_unavailable_rebuild_engine')

    def capture(self, path):
        from .screenshots import save_bgra
        frame = self.fresh()
        return save_bgra(path, frame['bgra'], frame['width'], frame['height'], bottom_up=True)
