"""Engine-owned 48 kHz timeline and loss-detecting stereo PCM ring."""
import mmap
import os
import struct
import time

from .protocol import BridgeError


class MediaStream:
    rate, capacity, slots = 48000, 4096, 128

    def __init__(self, path):
        self.path = path
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            os.ftruncate(fd, 128+self.slots*(64+self.capacity*8))
            self.mapping = mmap.mmap(fd, 0)
        finally:
            os.close(fd)
        self.mapping[:128] = struct.pack('<8sII112x', b'ASTRAMD1', self.capacity, self.slots)

    def close(self):
        self.mapping.close()
        self.path.unlink(missing_ok=True)

    def get(self, offset, fmt='Q'):
        return struct.unpack_from('<'+fmt, self.mapping, offset)[0]

    @property
    def sequence(self): return self.get(24)

    @property
    def samples(self): return self.get(32)

    @property
    def audio(self): return self.get(40, 'I') == 1

    @property
    def active(self): return bool(self.get(44, 'I'))

    def ui(self, active):
        struct.pack_into('<I', self.mapping, 16, int(active))

    def request_recording(self, active):
        struct.pack_into('<I', self.mapping, 56, int(active))

    def recording(self, active, timeout=3):
        self.request_recording(active)
        deadline = time.monotonic()+timeout
        while self.get(60, 'I') != int(active):
            if time.monotonic() >= deadline:
                raise BridgeError('engine_media_ack_timeout')
            time.sleep(.002)
        return self.get(64 if active else 72)

    def read(self, sequence):
        offset = 128+((sequence-1) % self.slots)*(64+self.capacity*8)
        version, start, count = struct.unpack_from('<QQI', self.mapping, offset)
        if version != sequence*2: return None
        if not 0 < count <= self.capacity: raise BridgeError('audio_invalid_block')
        data = self.mapping[offset+64:offset+64+count*8]
        if self.get(offset) != version: return None
        return {'start':start, 'samples':count, 'pcm':data}
