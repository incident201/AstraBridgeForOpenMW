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

Capture interval statistics use a bounded lifetime histogram rather than
retaining and sorting every frame interval. `frame_interval_ms.median` and
`p95` are estimates: bins are 0.01 ms wide through 100 ms and grow by 1% above
that. `max` retains the exact observed maximum, rounded to three decimal places.
Percentiles refresh at most once per second; reading telemetry does not become
more expensive as frame counts grow.

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
WebRTC to Desktop. The two viewer presets are 720p30 and 1080p60. Disabling game sound
produces a video-only live stream; it does not prevent viewing the game. Live H.264 uses
no B-frames; VAAPI uses its `constrained_baseline` profile spelling. The live
chain is probed separately from recording and can independently fall back to CPU.

Live transport follows wall time: during an engine pause it shows the last frame
and supplies viewer-only silence. It never advances benchmark media time.
Switching quality or disconnecting the viewer does not restart Recorder.

Slow live consumers discard stale media without blocking recording queues.
They still share CPU/GPU resources with the game, so actual performance is
reported rather than assuming 60 rendered frames per second on every machine.

## Viewer timeline and replay

The timeline below Live view lets a user seek through the current recording,
pause playback and resume it. **Go live** returns to the existing WebRTC stream.
These are viewing controls: they do not pause the engine, interrupt the agent,
stop recording or restart the container. Past footage cannot receive game input.
Entering replay releases held manual keys/buttons without relinquishing manual
ownership or changing the game's running state. The usual focus-loss and
connection-loss rules still apply.

The timeline follows recorded engine time, including the existing exclusion of
agent thinking pauses. Only fully written MP4 fragments are available, so the
latest playable recording position can lag the live view. With recording off,
the viewer can freeze its live picture, but has no recorded history to seek.

The daemon incrementally indexes the fragmented MP4 and serves its initialization
and complete media fragments. Desktop uses Media Source Extensions to buffer a
short interval around playback. Seeking elsewhere reads the corresponding GOPs
from the original file. No second encode, full recording copy or growing video
buffer in application memory is required. The reader recognizes atomic faststart
replacement at finalization and switches to range-based file playback. A paused
picture stays paused until the user resumes or seeks.

## Viewing and spectator overlays

Desktop connects the live viewer automatically when the game starts. Tab changes
keep the WebRTC connection alive; explicit disconnect stays off until reconnect.
Viewer preferences can show compact commentary, recent actions and session clocks.
These are presentation overlays and are not baked into benchmark MP4 frames.
During replay, overlays come from that recording's event sidecar at the playback
position. Seeking restores the corresponding messages, action state and clocks;
pausing freezes them. **Live** returns to current session events. The same history
is available in the saved recording player with the container stopped. A recording
without a timeline shows no historical overlay. Timeline controls affect viewing only.

Finalized recordings are browsed, played and exported directly from the host
recordings folder, even with a stopped or removed container. The list supports
all profiles or the selected profile. New filenames include the profile name;
`.context.json` preserves its original ID/name. `.events.jsonl` keeps comments
and action start/result events with session clocks and exact recording positions
on the engine media sample clock. Export it with **Export timeline** for later
synchronization. Legacy recordings remain readable without these sidecars.

Recording start seeds the history with the comments/actions already visible.
Periodic clock samples follow the engine media clock; complete JSONL records are
indexed incrementally, independently of MP4 capture/finalization. Thinking pauses
have no video duration, so events during such a pause share a recording position.
All those messages belong to that same frame; their wall timestamps retain order.

### Removing a recording

Select a video in **Recordings** and choose **Delete recording**. Confirmation
permanently removes the MP4, its commentary/action timeline, metadata and encoder
logs from the host folder. Other videos and game/profile data are kept. This
works while the container is stopped; it does not start the runtime. An unfinished
video cannot be removed while recording is active. The recordings folder can
still be opened directly with **Open folder**.

Commentary overlays display complete messages with line wrapping. When recent
messages exceed the available space, the overlay itself scrolls; the game view
keeps its size. Live, replay and fullscreen use the same overlay layout.
