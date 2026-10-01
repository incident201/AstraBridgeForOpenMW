"""Select a working H.264 encoder before the recording clock starts.

Production uses the pinned image FFmpeg. Development may override the binary.
All hardware paths still require a successful encode; no downloads happen here.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .protocol import BridgeError
from .gpu import resolve_gpu


VIDEO_FILTER = ('vflip,scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2:'
                'in_range=full:out_range=tv:out_color_matrix=bt709,'
                'pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1')
MODES = {'auto', 'cpu', 'vaapi', 'nvenc'}


def settings(local):
    mode = local.get('recording_encoder', 'auto')
    binary = local.get('ffmpeg_binary')
    device = local.get('vaapi_device')
    if not isinstance(mode, str) or mode not in MODES:
        raise BridgeError('invalid_recording_encoder')
    if any(value is not None and (not isinstance(value, str) or not value.strip()) for value in (binary, device)):
        raise BridgeError('invalid_recording_configuration')
    gpu = local.get('encoding_gpu', 'auto')
    if not isinstance(gpu, str) or gpu != 'auto' and not re.fullmatch(r'pci:[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]', gpu):
        raise BridgeError('invalid_encoding_gpu')
    if gpu != 'auto' and device:
        raise BridgeError('choose_encoding_gpu_or_vaapi_override')
    return {'mode': mode, 'binary': binary, 'device': device, 'gpu': gpu}


@dataclass(frozen=True)
class Encoder:
    binary: str
    codec: str
    version: str = ''
    device: str | None = None
    low_power: bool = False
    gpu_conversion: bool = False
    gpu_id: str | None = None
    cuda_index: int | None = None

    @property
    def hardware(self):
        return self.codec != 'libx264'

    def command(self, width, height, fps, path, audio=None):
        args = [self.binary, '-hide_banner', '-loglevel', 'error', '-n']
        if self.codec == 'h264_vaapi':
            args += ['-vaapi_device', self.device]
        args += ['-f', 'rawvideo', '-pixel_format', 'bgra', '-video_size', f'{width}x{height}',
                 '-framerate', str(fps), '-thread_queue_size', '128', '-i', 'pipe:0']
        if audio is not None:
            args += ['-f', 'f32le', '-ar', '48000', '-ac', '2', '-probesize', '32',
                     '-analyzeduration', '0', '-thread_queue_size', '128', '-i', str(audio),
                     '-c:a', 'aac', '-b:a', '384k']
        else:
            args += ['-an']
        filters = VIDEO_FILTER
        if self.codec == 'h264_vaapi':
            if self.gpu_conversion and (width, height) == (1920, 1080):
                filters = 'vflip,hwupload,scale_vaapi=format=nv12:out_color_matrix=bt709:out_range=tv,setsar=1'
            else:
                filters += ',format=nv12,hwupload'
        args += ['-filter_threads', '2', '-vf', filters, '-c:v', self.codec]
        if self.codec == 'libx264':
            args += ['-preset', 'veryfast', '-crf', '18', '-threads', '4', '-pix_fmt', 'yuv420p',
                     '-bf', '2', '-x264-params', 'open-gop=0']
        elif self.codec == 'h264_nvenc':
            args += ['-preset', 'p4', '-rc', 'constqp', '-qp', '18', '-pix_fmt', 'yuv420p', '-bf', '2']
            if self.cuda_index is not None:
                args += ['-gpu', str(self.cuda_index)]
        else:
            # CQP also works on Intel systems without HuC bitrate-control
            # firmware. Jasper Lake exposes only the low-power encoder.
            args += ['-rc_mode', 'CQP', '-qp', '18', '-low_power', str(int(self.low_power)), '-bf', '0']
        args += ['-profile:v', 'high', '-level:v', '4.2', '-flags', '+cgop', '-g', str(fps // 2),
                 '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
                 '-movflags', '+frag_keyframe+delay_moov+default_base_moof',
                 '-use_editlist', '1', '-avoid_negative_ts', 'disabled', str(path)]
        return args

    def info(self):
        try:
            with Path(self.binary).open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        except OSError:
            digest = None
        return {'encoder': self.codec, 'hardware_accelerated': self.hardware,
                'ffmpeg_path': self.binary, 'ffmpeg_version': self.version, 'ffmpeg_sha256': digest,
                'encoder_device': self.device, 'encoder_low_power': self.low_power if self.codec == 'h264_vaapi' else None,
                'gpu_color_conversion': self.gpu_conversion,
                'gpu_id': self.gpu_id, 'cuda_device_index': self.cuda_index,
                'quality_mode': 'cqp' if self.hardware else 'crf', 'quality': 18}


def binaries(preferred=None):
    pinned = os.environ.get('ASTRA_FFMPEG')
    if os.environ.get('ASTRA_MODE') == 'production':
        if preferred or os.environ.get('IMAGEIO_FFMPEG_EXE'):
            raise BridgeError('development_override_in_production')
        if not pinned or not Path(pinned).is_file(): raise BridgeError('runtime_ffmpeg_missing')
        return [pinned], False
    if pinned and not preferred and not os.environ.get('IMAGEIO_FFMPEG_EXE'):
        return [pinned], False
    explicit = preferred or os.environ.get('IMAGEIO_FFMPEG_EXE')
    if explicit:
        value = os.path.expanduser(explicit)
        return [str(Path(shutil.which(value) or value).resolve())], True
    import imageio_ffmpeg
    # imageio prefers its packaged binary. Keep it last for GPU discovery and
    # first for CPU fallback, so a CPU-only system FFmpeg does not replace it.
    result = []
    for value in (shutil.which('ffmpeg'), imageio_ffmpeg.get_ffmpeg_exe()):
        if value:
            path = str(Path(value).resolve())
            if path not in result:
                result.append(path)
    return result, False


def devices(preferred=None):
    if preferred:
        return [str(Path(preferred).expanduser())]
    result=[str(p) for p in sorted(Path('/dev/dri').glob('renderD*')) if os.access(p, os.R_OK | os.W_OK)]
    if os.environ.get('ASTRA_GPU_BACKEND')=='wsl' and os.environ.get('DISPLAY'):
        result.append(os.environ['DISPLAY'])
    return result


def available(binary):
    result = subprocess.run([binary, '-hide_banner', '-encoders'], capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise ValueError((result.stderr or result.stdout)[-1500:])
    names = set(re.findall(r'^\s*[A-Z.]{6}\s+(\S+)', result.stdout, re.M))
    version = subprocess.run([binary, '-version'], capture_output=True, text=True, timeout=5)
    return names, (version.stdout.splitlines() or ['unknown'])[0][:300]


def probe(encoder, first, fps, sound, directory):
    # Exercise the actual BGRA conversion, GPU upload, codec, AAC and MP4
    # muxer. An encoder listed by FFmpeg may still lack a usable device/driver.
    with tempfile.TemporaryDirectory(prefix='.encoder-probe-', dir=directory) as temporary:
        temporary = Path(temporary)
        output = temporary / 'probe.mp4'
        audio = None
        if sound:
            audio = temporary / 'silence.f32'
            audio.write_bytes(bytes((round(48000 * 4 / fps) + 2048) * 8))
        args = encoder.command(first['width'], first['height'], fps, output, audio)
        args[-1:-1] = ['-frames:v', '4', '-t', str(4 / fps)]
        result = subprocess.run(args, input=first['bgra'] * 4, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, timeout=10)
        if result.returncode or not output.is_file() or output.stat().st_size < 100:
            return False, result.stderr.decode(errors='replace')[-1500:] or 'No encoded MP4 produced'
        return True, None


def select(first, fps, sound, directory, options=None):
    options = options or settings({})
    mode = options['mode']
    # An explicit physical device must never silently select another GPU.
    # Auto encoder mode may still fall back to CPU if its real probe fails.
    gpu_id = options.get('gpu', 'auto')
    selected = resolve_gpu(gpu_id) if mode != 'cpu' and gpu_id != 'auto' else None
    candidates, explicit = binaries(options.get('binary'))
    catalog = {}; attempts = []
    for binary in candidates:
        try:
            catalog[binary] = available(binary)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            attempts.append({'ffmpeg': binary, 'error': str(exc)[-1500:]})
    def works(encoder):
        try:
            ok, error = probe(encoder, first, fps, sound, directory)
        except (OSError, subprocess.TimeoutExpired) as exc:
            ok, error = False, str(exc)[-1500:]
        attempts.append({'ffmpeg': encoder.binary, 'encoder': encoder.codec, 'device': encoder.device,
                         'gpu_id': encoder.gpu_id, 'cuda_device_index': encoder.cuda_index,
                         'low_power': encoder.low_power, 'gpu_conversion': encoder.gpu_conversion, 'ok': ok, 'error': error})
        return ok
    if mode != 'cpu':
        nodes = ([selected['render_node']] if selected.get('render_node') else []) if selected else devices(options.get('device'))
        nvenc_allowed = selected is None or selected.get('nvenc_index') is not None
        if selected and not nvenc_allowed and not nodes:
            attempts.append({'gpu_id': gpu_id, 'ok': False, 'error': 'No accessible encoding device for selected GPU'})
        def nvenc(binary, version):
            return Encoder(binary, 'h264_nvenc', version, gpu_id=selected['id'] if selected else None,
                           cuda_index=selected['nvenc_index'] if selected else None)
        for binary, (names, version) in catalog.items():
            if sound and 'aac' not in names:
                continue
            wsl=os.environ.get('ASTRA_GPU_BACKEND')=='wsl'
            if nvenc_allowed and not wsl and mode in {'auto', 'nvenc'} and 'h264_nvenc' in names:
                encoder = nvenc(binary, version)
                if works(encoder):
                    return encoder, attempts
            if mode in {'auto', 'vaapi'} and 'h264_vaapi' in names:
                for device in nodes:
                    for low_power in (True, False):
                        for gpu_conversion in ((True, False) if (first.get('width'), first.get('height')) == (1920,1080) else (False,)):
                            encoder = Encoder(binary, 'h264_vaapi', version, device, low_power, gpu_conversion,
                                              gpu_id=selected['id'] if selected else None)
                            if works(encoder):
                                return encoder, attempts
            if nvenc_allowed and wsl and mode in {'auto','nvenc'} and 'h264_nvenc' in names:
                encoder=nvenc(binary,version)
                if works(encoder):return encoder,attempts
    if mode in {'auto', 'cpu'}:
        for binary in reversed(candidates):
            names, version = catalog.get(binary, (set(), ''))
            if 'libx264' in names and (not sound or 'aac' in names):
                encoder = Encoder(binary, 'libx264', version)
                if works(encoder):
                    return encoder, attempts
    raise BridgeError('recording_encoder_unavailable', requested_encoder=mode,
                      explicit_ffmpeg=explicit, attempts=attempts)
