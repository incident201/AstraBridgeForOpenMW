# Recording and screenshot storage

Read this when starting, stopping or diagnosing a recording, or when a cached image has expired. All commands follow `astrabridge game`.

## Screenshot storage

Runtime screenshots are a rolling cache: the latest 128 by default. The user can configure `screenshot_keep` (integer ≥8) through runtime settings. Screenshots explicitly attached by `remember` are protected; those notes retain up to six views each. Old automatic atlas links are returned only while their image exists. SQLite paths, nodes, names and door links survive cache cleanup. The CLI downloads returned images into a local export directory; use the returned files to inspect appearances and obstacles. The atlas stores travel knowledge, not a substitute rendered view.

Map SVG/PNG files are generated only with `observe --map` or `atlas --map`. The atlas map reuses `atlas-current.svg/png`; other generated maps have an eight-file cache. User-named files and recordings are not pruned.

## Recording

`record-start` starts a new MP4 in the configured directory. `record-status` reports its path, recording/capture state and errors. `record-stop` finalizes it for upload; successful nonempty recordings report `upload_ready:true`. Finalization copies encoded streams without recompressing, and may take time for large files.

The default is 1920×1080 at 60 fps: H.264 High, BT.709, 4:2:0, and stereo AAC-LC at 48 kHz / 384 kbps. Encoder selection is automatic: check the returned metadata for the actual encoder and quality mode (software CRF 18 or hardware CQP 18; these are different measures). The final MP4 uses fast start and no edit lists. Active gameplay and UI work are included. Thinking pauses freeze the native sound mix as well as the recording clock, preserving music, voices, effects and reverberation. `look` and `scan` remain real recorded turns. There is no hidden camera inspection mode. Sound is controlled by the user's runtime configuration.

The Desktop live viewer is independent of recording. Its 720p30/1080p60 choice,
connection and displayed waiting time do not change the recording timeline.
Its replay timeline, playback pause and **Go live** button are viewer controls;
they do not issue game actions or pause the agent. Continue using current
`observe` results even when the user is watching past footage. There is no replay
command to substitute for `record-start` or `record-stop`.
The CLI downloads returned screenshots to local export files. Recordings are
written directly to the selected host recordings folder, and the CLI returns
those direct paths. Do not enter the container to find runtime files. If
`artifact_error` is reported, the action itself may still have completed: inspect
its result/receipt instead of repeating the mutation. Request a fresh observation
if an image is needed.

Video and audio share the engine's sample clock; speaker latency does not alter the recording. `rendered_frames`, `repeated_frames`, `ring_dropped_frames`, `encoder_queue_peak` and `frame_interval_ms` expose capture performance. Audio gaps/overruns are explicit errors. `av_difference_ms` compares encoded video duration with source audio duration, including final frame rounding; it is not a measurement of audible lip sync. `audio_monitor` reports speaker availability; monitoring failure does not discard recorded audio. An empty recording has no uploadable video.

Keep the private engine render resolution stable during recording. Resizing Desktop or entering its Fullscreen view does not resize that render surface. `video_window_resized` requires a new recording. Matching native engine hooks are required. Screenshots use completed frames and are resized before PNG encoding, so no full-size screenshot files accumulate. All public pixel inputs, `rect` and `aim_point` use screenshot coordinates; `screen.render_width/render_height` describe the separate game/video dimensions. Existing screenshot retention applies.

Recording is fragmented while active for crash recovery. Normal stop prepares the upload file; if finalization fails, the original capture is preserved and the error is reported. Do not claim a recording succeeded without checking its final status. No automatic upload or file-size limit is imposed.

## Commentary and action timeline

`astrabridge game comment "I will check the eastern door next."` publishes a
spectator message while connected. It can be sent during an outstanding action;
it does not take input ownership, observe, capture a screenshot or change pause
state. Text must be nonempty and at most 4096 UTF-8 bytes. Keep comments brief
and useful; do not send hidden reasoning or repeat every tool call. Action
history is collected automatically. Ordinary messages in your external chat
are not forwarded unless you also use this command.

The response includes `session`, `wall_seconds` (agent-connected time),
`game_seconds` (engine simulation time), and, during recording,
`recording` / `recording_seconds` (position on its source-media timeline).
Thinking pauses count toward wall time, not simulation time or paused media.
The profile stores a session timeline; recordings receive `.events.jsonl`
sidecars. Desktop can toggle commentary, action history and clock overlays.
Overlays do not change the recorded video. During replay, Desktop displays the
historical comments/actions and clocks at that recording position, not live events. Viewer replay does not change these
live command timestamps. Commentary is presentation history, not task memory;
use `knowledge checkpoint` or notes for information needed after context loss.
