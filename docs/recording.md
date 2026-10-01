# Recording and live media

## Files on the host

Recordings are written directly to a host directory selected at installation.
The default is `<managed storage>/recordings`; `install --recordings DIRECTORY`
selects another location. The runtime mounts only this directory at
`/data/recordings`. Raw frame/audio buffers, saves and internal databases remain
in Linux managed storage.

MP4 files and their sidecars are therefore available in the host file manager,
including when Desktop is closed. The recording browser has an **Open folder**
action. `astrabridge recordings` reports the directory; completed gameplay
recording commands return direct host file paths. No manual container access is
needed. The chosen mount is part of the installation configuration.

While recording, the MP4 is fragmented and may be incomplete. A successful
normal stop remuxes encoded streams into a faststart MP4 without re-encoding.
Check `upload_ready` before treating it as a finished upload. If finalization
fails, the recoverable original and diagnostic files remain available.

## Sources and clock

OpenMW publishes completed BGRA frames through FrameStream and stereo float32
PCM through MediaStream. Both carry positions on the engine-owned 48 kHz sample
clock. Recorder and FramePacer consume these directly; the Desktop compositor
and WebRTC are not recording sources.

Thinking pauses do not advance this clock. FramePacer produces a constant
60 fps output, choosing completed frames and repeating them when actual game FPS
is lower. Metadata reports actual rendered/repeated/lost frames. Missing expected
audio is an error; it is not silently replaced with silence.

Live subscribers can request PCM independently of recording. Recording's native
start/end acknowledgements remain separate. Recorder clips shared audio blocks
to its acknowledged sample interval, including when a live subscriber was
already active or remains connected afterward.

## Pinned FFmpeg and encoder selection

The OCI image supplies one FFmpeg binary with libx264, VAAPI, NVENC, AAC, Opus
and the required video filters. Production never searches the host PATH and
does not use imageio-ffmpeg. Version, build options and binary SHA256 are part of
runtime and recording identity. Development may explicitly override the binary.

Modes remain `auto`, `cpu`, `vaapi` and `nvenc`. Availability requires a real
four-frame encode using the first fresh engine frame, real conversion/upload
chain, selected device, AAC and MP4 output. An encoder name in `-encoders` is
only a candidate. VAAPI tries device, low-power and GPU conversion combinations.
Auto falls back to libx264 when hardware probes fail.

Linux prefers working NVENC and then VAAPI devices. WSL prefers D3D12/VAAPI,
with optional NVENC and CPU fallback. Each path requires a successful real-frame
encoder probe on the selected device.

| Encoder | Recording baseline |
|---|---|
| libx264 | Veryfast, CRF 18, four threads, two B-frames |
| NVENC | CQP/QP 18, preset p4, two B-frames |
| VAAPI | CQP/QP 18, probed low-power mode, no B-frames |

Output is 1920×1080/60, H.264 High Level 4.2, 4:2:0, BT.709/TV range and square
pixels. Scaling preserves aspect ratio and pads as needed. Audio is stereo
48 kHz AAC at 384 kbps. Hardware CQP and software CRF are distinct quality modes,
not equivalent quality scores.

Sidecars retain encoder attempts, actual device/conversion/quality selection,
FFmpeg diagnostics, frame/audio statistics and environment information.

## Live viewer

A separate FFmpeg process publishes H.264/Opus to private MediaMTX, which serves
WebRTC to Desktop. The two viewer presets are 720p30 and 1080p60. Live H.264 uses
no B-frames; VAAPI uses its `constrained_baseline` profile spelling. The live
chain is probed separately from recording and can independently fall back to CPU.

Live transport follows wall time: during an engine pause it shows the last frame
and supplies viewer-only silence. It never advances benchmark media time.
Switching quality or disconnecting the viewer does not restart Recorder.

Slow live consumers discard stale media without blocking recording queues.
They still share CPU/GPU resources with the game, so actual performance is
reported rather than assuming 60 rendered frames per second on every machine.
