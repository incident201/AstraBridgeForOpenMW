# Recording, screenshots and commentary

Read this when managing a recording, sending spectator commentary or recovering
an expired image. All commands follow `astrabridge game`.

## Screenshots

Use returned image paths for visual inspection. Runtime screenshots are a rolling
cache; old automatic Atlas images can expire while the remembered routes remain.
Images attached to an explicit `remember` note are protected. A historical image
never establishes the current position or supplies fresh action handles.

`observe --map` and `atlas --map` additionally produce navigation diagrams;
`map local` and `map world` return the game's own map image. See [maps](maps.md).

If an image is missing or `artifact_error` is reported, the game action may still
have completed. Inspect its result or receipt before retrying. Request a new
observation when a current image is needed.

## Recording

| Command | Result |
|---|---|
| `record-start` | Start recording to a new file in the user's configured recordings folder. |
| `record-status` | Read its path, duration, recording/capture state and errors. |
| `record-stop` | Finalize the recording. Successful nonempty output reports `upload_ready:true`; check errors before claiming success. |
| `record-status --full` | Read additional recording diagnostics when reporting a problem. |

Recording normally produces 1080p60 video with game audio. Encoder selection is
automatic. Gameplay and UI actions are included; thinking pauses do not add idle
video time. Turns from `look` and `scan` are recorded too.

Recordings are saved to the host's configured folder. Use the returned path;
container access is unnecessary. Finalization can take time for a long file.
There is no automatic upload.

Desktop viewer quality, replay position and playback pause do not control the
game or recording. Keep using current action observations even while the user
is reviewing earlier footage.

## Commentary and action timeline

`comment "I will check the eastern door next."` publishes a spectator message.
It can be sent while an action is running and does not pause or advance the
game. Text must be nonempty and at most 4096 UTF-8 bytes. Use brief progress
updates, discoveries or changes of approach; do not repeat every tool call or
send private reasoning. Tool actions are logged automatically. External chat
messages are not captured unless also sent with `comment`.

The result includes `wall_seconds` (agent-connected time), `game_seconds`
(simulation time) and, during recording, `recording_seconds`. Thinking counts
as wall time but not simulation time. Desktop can display comments, actions and
clocks as optional overlays, synchronized with replay. These overlays do not
become part of the recorded video.

Comments are spectator history, not task memory. Use `knowledge checkpoint`
or notes for information needed after context loss.
