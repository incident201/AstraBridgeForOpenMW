import subprocess

import pytest

from astra_bridge import encoding as E
from astra_bridge.protocol import BridgeError


@pytest.fixture
def selection(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(E, 'binaries', lambda preferred: (['system', 'bundled'], False))
    monkeypatch.setattr(E, 'devices', lambda preferred: ['render128', 'render129'])
    monkeypatch.setattr(E, 'available', lambda binary: ({'h264_nvenc', 'h264_vaapi', 'libx264', 'aac'}
                                                     if binary == 'system' else {'libx264', 'aac'}, 'test version'))
    def run(works, mode='auto', first=None):
        def probe(encoder, *args):
            calls.append(encoder)
            return works(encoder), 'unusable driver'
        monkeypatch.setattr(E, 'probe', probe)
        encoder, attempts = E.select(first or {}, 60, True, tmp_path, E.settings({'recording_encoder': mode}))
        return encoder, calls, attempts
    return run


def test_nvidia_is_used_only_after_a_successful_encode(selection):
    encoder, calls, attempts = selection(lambda e: e.codec == 'h264_nvenc')
    assert encoder.binary == 'system' and encoder.hardware
    assert len(calls) == 1 and attempts[0]['ok']


def test_vaapi_works_without_a_vendor_name_assumption(selection):
    encoder, calls, attempts = selection(lambda e: e.codec == 'h264_vaapi' and not e.low_power)
    assert encoder.codec == 'h264_vaapi' and encoder.device == 'render128' and not encoder.low_power
    assert [e.codec for e in calls] == ['h264_nvenc', 'h264_vaapi', 'h264_vaapi']
    assert not attempts[0]['ok']


def test_other_render_nodes_are_tried_before_cpu(selection):
    encoder, calls, _ = selection(lambda e: e.device == 'render129' and e.low_power)
    assert encoder.hardware and encoder.device == 'render129'
    assert all(e.codec != 'libx264' for e in calls)


def test_vaapi_without_rgb_vpp_keeps_hardware_encoding(selection):
    encoder, calls, _ = selection(lambda e: e.codec == 'h264_vaapi' and not e.gpu_conversion,
                                 first={'width':1920,'height':1080})
    assert encoder.hardware and not encoder.gpu_conversion
    assert calls[1].gpu_conversion and not calls[2].gpu_conversion


@pytest.mark.parametrize('sound', [True,False])
def test_external_encoder_without_aac_is_used_only_for_silent_recording(monkeypatch, tmp_path, sound):
    monkeypatch.setattr(E, 'binaries', lambda _: (['system','bundled'], False))
    monkeypatch.setattr(E, 'available', lambda binary: ({'h264_nvenc'} if binary=='system' else {'libx264','aac'}, 'version'))
    monkeypatch.setattr(E, 'devices', lambda _: [])
    monkeypatch.setattr(E, 'probe', lambda *args: (True,None))
    encoder, _ = E.select({},60,sound,tmp_path)
    assert encoder.hardware == (not sound)


def test_broken_hardware_falls_back_to_bundled_cpu(selection):
    encoder, calls, _ = selection(lambda e: e.codec == 'libx264')
    assert encoder.binary == 'bundled' and not encoder.hardware
    assert calls[-1].codec == 'libx264' and all(e.hardware for e in calls[:-1])


def test_cpu_override_does_not_probe_gpus(selection):
    encoder, calls, _ = selection(lambda e: True, 'cpu')
    assert encoder.binary == 'bundled' and len(calls) == 1 and not encoder.hardware


def test_forced_gpu_failure_is_explicit_instead_of_silent_cpu(selection):
    with pytest.raises(BridgeError, match='recording_encoder_unavailable') as exc:
        selection(lambda e: e.codec == 'libx264', 'vaapi')
    assert exc.value.details['requested_encoder'] == 'vaapi'
    assert all(a.get('encoder') == 'h264_vaapi' for a in exc.value.details['attempts'])


def test_missing_system_ffmpeg_or_driver_does_not_break_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(E, 'binaries', lambda _: (['missing-system', 'bundled'], False))
    def available(binary):
        if binary == 'missing-system':
            raise OSError('missing library')
        return {'libx264', 'aac'}, 'bundled version'
    monkeypatch.setattr(E, 'available', available)
    monkeypatch.setattr(E, 'devices', lambda _: [])
    monkeypatch.setattr(E, 'probe', lambda *a: (True, None))
    encoder, attempts = E.select({}, 60, True, tmp_path)
    assert encoder.binary == 'bundled' and attempts[0]['error'] == 'missing library'


def test_probe_timeout_allows_fallback(selection):
    def works(e):
        if e.hardware:
            raise subprocess.TimeoutExpired('ffmpeg', 10)
        return True
    encoder, _, _ = selection(works)
    assert not encoder.hardware


def test_explicit_binary_and_environment_override_are_honoured(tmp_path, monkeypatch):
    import imageio_ffmpeg
    monkeypatch.setattr(E.shutil, 'which', lambda value: None)
    monkeypatch.setattr(imageio_ffmpeg, 'get_ffmpeg_exe', lambda: pytest.fail('must honour explicit binary'))
    monkeypatch.setenv('IMAGEIO_FFMPEG_EXE', str(tmp_path / 'environment-ffmpeg'))
    paths, explicit = E.binaries(str(tmp_path / 'configured-ffmpeg'))
    assert paths == [str(tmp_path / 'configured-ffmpeg')] and explicit
    assert E.binaries()[0] == [str(tmp_path / 'environment-ffmpeg')]


def test_default_discovery_prefers_system_for_gpu_and_retains_bundle(tmp_path, monkeypatch):
    import imageio_ffmpeg
    monkeypatch.delenv('IMAGEIO_FFMPEG_EXE', raising=False)
    monkeypatch.setattr(E.shutil, 'which', lambda _: str(tmp_path / 'system'))
    monkeypatch.setattr(imageio_ffmpeg, 'get_ffmpeg_exe', lambda: str(tmp_path / 'bundled'))
    paths, explicit = E.binaries()
    assert paths == [str(tmp_path / 'system'), str(tmp_path / 'bundled')] and not explicit


@pytest.mark.parametrize('value', [None, False, 'unknown'])
def test_invalid_encoder_configuration_fails_early(value):
    with pytest.raises(BridgeError, match='invalid_recording_encoder'):
        E.settings({'recording_encoder': value})


def test_probe_rejects_success_exit_without_an_encoded_file(tmp_path, monkeypatch):
    monkeypatch.setattr(E.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, stderr=b''))
    ok, reason = E.probe(E.Encoder('ffmpeg', 'h264_nvenc'), {'width':2, 'height':2, 'bgra':bytes(16)}, 60, True, tmp_path)
    assert not ok and reason == 'No encoded MP4 produced' and not list(tmp_path.iterdir())


def test_cpu_probe_really_encodes_bgra_and_aac_without_gpu(tmp_path):
    import imageio_ffmpeg
    encoder = E.Encoder(imageio_ffmpeg.get_ffmpeg_exe(), 'libx264')
    assert E.probe(encoder, {'width':32, 'height':32, 'bgra':bytes((30,80,100,255))*1024}, 60, True, tmp_path) == (True, None)
    assert not list(tmp_path.iterdir())


def test_hardware_quality_is_not_reported_as_software_crf():
    for codec in ('h264_vaapi', 'h264_nvenc'):
        info = E.Encoder('/not-installed', codec).info()
        assert info['hardware_accelerated'] and info['quality_mode'] == 'cqp'
    assert E.Encoder('/not-installed', 'libx264').info()['quality_mode'] == 'crf'
