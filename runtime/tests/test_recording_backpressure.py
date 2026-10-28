"""PCM must keep draining while the video queue is temporarily full."""
import queue
import threading
import pytest

from astra_bridge.protocol import BridgeError
from astra_bridge.recording import Recorder


class AudioRing:
    slots = 4

    def __init__(self):
        self.sequence = 0
        self.blocks = {}

    def produce(self):
        self.sequence += 1
        self.blocks[self.sequence] = {'start': (self.sequence-1)*480,
                                      'samples': 480, 'pcm': bytes(480*8)}
        self.blocks.pop(self.sequence-self.slots, None)

    def read(self, sequence):
        return self.blocks.get(sequence)


class BackpressuredVideo:
    """Advance a synthetic producer during each bounded queue wait."""
    def __init__(self, ring, clock, ready_at=.12):
        self.ring, self.clock, self.ready_at = ring, clock, ready_at
        self.frames = []

    def put(self, value, timeout):
        until = min(self.clock[0]+timeout, self.ready_at)
        while self.clock[0]+.009 < until:
            self.clock[0] += .01
            self.ring.produce()
        if self.clock[0]+.001 < self.ready_at:
            raise queue.Full
        self.frames.append(value)

    def qsize(self):
        return len(self.frames)


def recorder():
    result = Recorder.__new__(Recorder)
    result.condition = threading.Condition()
    result.media = AudioRing()
    result.base_sample = result.audio_samples = result.audio_cursor = 0
    result.end_sample = None
    result.audio_queue = queue.Queue(maxsize=256)
    result.queue_high_water = 0
    result.error = None
    return result


def test_video_backpressure_longer_than_ring_capacity_does_not_lose_pcm(monkeypatch):
    r = recorder()
    clock = [0.]
    r.queue = BackpressuredVideo(r.media, clock)
    monkeypatch.setattr('astra_bridge.recording.time.monotonic', lambda: clock[0])
    r._enqueue({'bgra': b'video'})
    r._audio()
    assert r.media.sequence > r.media.slots
    assert r.audio_cursor == r.media.sequence
    assert r.audio_samples == r.media.sequence*480
    assert r.audio_queue.qsize() == r.media.sequence
    assert r.queue.frames == [b'video']


def test_permanently_stalled_video_fails_with_video_diagnostic_while_draining_audio(monkeypatch):
    r = recorder()
    clock = [0.]
    r.queue = BackpressuredVideo(r.media, clock, ready_at=1.)
    monkeypatch.setattr('astra_bridge.recording.time.monotonic', lambda: clock[0])
    with pytest.raises(BridgeError, match='video_encoder_too_slow'):
        r._enqueue({'bgra': b'video'})
    assert r.audio_samples > 0
    assert .25 <= clock[0] < .27


def test_completed_recording_ignores_later_live_audio_even_after_ring_wrap():
    r = recorder()
    r.base_sample = 120
    r.end_sample = 1200
    for _ in range(3):
        r.media.produce()
    r._audio()
    assert r.audio_samples == 1080 and r.audio_cursor == 3
    for _ in range(20):
        r.media.produce()
    r._audio()
    assert r.audio_samples == 1080 and r.audio_cursor == 3


def test_missing_expected_audio_still_fails_instead_of_inserting_silence():
    r = recorder()
    for _ in range(r.media.slots+1):
        r.media.produce()
    with pytest.raises(BridgeError, match='audio_ring_overrun'):
        r._audio()
    r = recorder()
    r.media.produce()
    r.media.blocks[1]['start'] = 480
    with pytest.raises(BridgeError, match='audio_sample_gap'):
        r._audio()
