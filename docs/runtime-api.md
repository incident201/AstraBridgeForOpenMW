# Runtime API and application interfaces

Desktop and its CLI mode share Application Core, connection configuration and
the same API client. Gameplay commands are grouped under `astrabridge game`.
Their options come from the Python command catalog, exported into the Desktop
package during its build. Host lifecycle commands also validate prerequisites
before install/start/update. A failed check returns `error: prerequisites_missing`,
a readable `message`, and `prerequisites` containing `available`, `version` and
`checks` (`id`, `title`, `status`, `detail`, optional `remedy`). This is an
Application Core result; it does not require a running daemon. Desktop presents
the same report in **Setup → System requirements**.

The Windows backend reads WSLC's structured inspection results. Container
existence does not depend on the language of Windows diagnostic messages;
service/connection failures are reported rather than treated as missing data.

## Connection

The default host ports are `127.0.0.1:18770` for HTTP/WebSocket and
`127.0.0.1:18771` for WebRTC ICE/TCP. They are not LAN/Internet listeners.

Except for `/health`, HTTP and WebSocket handshakes require
`Authorization: Bearer <installation token>`. The Desktop main process holds
this credential; the renderer calls its narrow preload interface. Game commands
also send `X-Astra-Session: <current agent token>`.

JSON responses use `{ "ok": true, "result": ... }` or
`{ "ok": false, "error": "code", ... }`. Artifact downloads and WHEP exchanges
retain their native binary/SDP formats. Clients must not automatically repeat
mutations after a connection failure; use the existing action receipt mechanism.

## Endpoints

| Method and path | Purpose |
|---|---|
| `GET /health` | Readiness and API/release identity; does not start the game. |
| `GET /v1/runtime/status` | Engine, owner, current action, recording/viewer and graphics state. |
| `POST /v1/runtime/engine/{start,stop,restart}` | Engine lifecycle inside the persistent daemon. |
| `GET/PATCH /v1/runtime/config` | Explicit runtime configuration; stop the game before editing. |
| `POST /v1/runtime/import-ini` | Import content/archive order using an explicitly selected encoding. |
| `POST /v1/agent/connect` | Acquire agent ownership; accepts `name` and optional expected `profile` ID. |
| `GET /v1/runtime/profiles` | Active profile and profile catalog. |
| `POST /v1/runtime/profiles/{create,rename,duplicate,switch,delete}` | Manage profiles while the game is stopped. Create takes `name`; rename/duplicate take `id,name`; switch/delete take `id`. |
| `POST /v1/agent/disconnect` | Stop held input and release the authenticated agent session. |
| `GET /v1/agent/status` | Public ownership state, without its credential. |
| `POST /v1/runtime/agent/end` | Deliberate user termination of the current owner. |
| `GET /v1/game/schema` | Public command catalog. |
| `POST /v1/game/command` | Execute `{ "op": "...", "args": {...} }` as the connected agent. |
| `POST /v1/runtime/recording/{start,stop,status}` | Recording management. |
| `GET /v1/runtime/replay?id=...` | Current recording's viewer timeline, or a previously identified recording; reads completed file data only. |
| `GET /v1/runtime/replay/{id}/{generation}/index?time=...` | A bounded batch of fragments around a recording time; `after=INDEX` requests following fragments. |
| `GET /v1/runtime/replay/{id}/{generation}/{init,INDEX}` | MP4 initialization or a complete media fragment; rejects stale file generations. |
| `GET /v1/runtime/recordings` | Recording inventory and artifact references. |
| `GET /v1/runtime/atlas` | Retained travel information; supports location, paging and map queries. |
| `GET /v1/runtime/environment` | Image/build identity and graphics diagnostics. |
| `GET /v1/runtime/sessions` | Recent lifecycle/ownership events. |
| `GET /v1/runtime/logs?name=...` | Named diagnostic logs; no arbitrary path reads. |
| `GET /v1/artifacts/{id}` | Registered screenshot, map, video or sidecar; supports HTTP range requests. |
| `POST/DELETE /v1/runtime/live` | Start/change or stop live video; `quality` is `720p30` or `1080p60`. |
| `POST /v1/runtime/live/whep` | WebRTC SDP offer/answer through MediaMTX. |
| `PATCH/DELETE /v1/runtime/live/whep/{id}` | WHEP session signaling/cleanup. |
| `GET /v1/events` | WebSocket events, telemetry and authenticated manual input. |

The Game API preserves the existing observation projection, object recognition,
normal UI callbacks and action validation. Runtime management does not become
an alternate gameplay knowledge API; the skill still restricts gameplay agents
to their intended public operations and observed information.

## Action outcome summaries

Ordinary action responses and composed `sequence`/`revisit` results include a
`summary` derived from the full result before output compaction. It mirrors the
effective feedback status/reason, normalizes time-limit termination separately,
and retains encountered blocking categories, stalled-attempt counts and measured
horizontal endpoint displacement. Navigation commands also report whether their
destination was reached. Historical blockers do not imply a currently blocked
endpoint, and a zero displacement alone does not identify an obstacle.

Direct horizontal input is assessed in the horizontal plane; vertical motion
cannot satisfy it. `act`, directed `jump` and `air-move` use a 0.05 m tolerance
and allow inputs shorter than 0.2 simulation seconds for acceleration/frame
latency. Failure is `no_horizontal_progress`, with confirmed independent side
effects retained. The original 3D `motion.moved_m` field keeps its meaning.

Composed results retain child feedback and summaries. Sequence feedback preserves
negative child outcomes; unmet explicit expectations fail the sequence, time
limits are partial, and remaining steps do not execute. The optional
`expect.min_horizontal_displacement_m` checks one step's finite nonnegative
minimum displacement; missing/discontinuous measurements fail rather than being
substituted with zero. `stopped_step` is one-based and can identify a step whose
execution never started. Existing completed/total action counts are retained.

The summary can also be read from a durable receipt with
`action-result REQUEST_ID --section summary`, without advancing the game.

The sequence/revisit endpoint metric uses only the player's positions already
observed for the Atlas, in one unchanged coordinate frame. It is not the sum of
step distances and is unavailable across observed transitions or timeline/frame
resets. Raw coordinates are not exposed. Revisit also records bounded attempt
reasons separately from motor steps, preserving earlier obstruction evidence
when a later attempt consumes the remaining time. These changes do not alter the
route planner, engine physics or retry policy. The [response reference](../skill/references/commands.md#keep-outcome-diagnostics-in-wrappers)
describes the fields and a wrapper that preserves diagnostics.

## Working-task memory

The Game API accepts `knowledge` with `action: checkpoint` and a nested
`checkpoint` JSON object, or `action: brief`. CLI equivalents are
`astrabridge game knowledge checkpoint 'JSON'` and `astrabridge game knowledge brief`.
The checkpoint contains agent-authored `goal`, `next_step`, optional
`status` (`open`, `done`, `abandoned`), `evidence_refs`, `note_refs`, `object_refs`,
`place_refs` and `failed_attempts`. It never derives quest answers or reads hidden
engine state. Bounds and usage are in the [memory reference](../skill/references/memory.md#current-working-state).

An additive `working_checkpoints` table in the existing knowledge database holds
one current record per Atlas playthrough namespace, inside the active Desktop
profile. Writes replace the payload atomically and increment a revision. References
must resolve to already-public memory in the appropriate scope; transient handles
are rejected. Brief reads are bounded, include short linked previews and do not
advance simulation or capture images. Full evidence remains available through
the existing knowledge commands.

`agent connect` and observations include `working_memory`: `available`, and when
present, `revision` and `needs_revalidation`. The full goal and notes are retrieved
only on request. Compaction of model history and prompt caching remain the external
agent's responsibility; AstraBridge does not call a model to summarize the task.

Every successful public load creates a new continuation branch. An earlier
checkpoint remains available but requires revalidation until the agent writes a
new checkpoint. Reading does not acknowledge it; replaying a previous command
receipt does not execute another write. Existing note statuses and evidence are
preserved. A new game starts a fresh Atlas namespace, new Desktop profiles start
empty, and explicit profile duplication copies the database into independent
storage. No save-file parsing or engine patch is involved.

## WebSocket input

The application sends `manual.acquire`, `manual.release`, or an `input` envelope
with an `event`. Input event types are `key`, `button`, `pointer`, `relative`,
`wheel`, `text` and `release`. Absolute pointer coordinates are normalized to the
displayed game area; relative movements are bounded pixel deltas. Key events use
DOM physical key codes. Only the owning manual connection can submit input.

Server events include `status`, `input.owner` and `error`. Status updates carry
action progress and separate game/capture/viewer metrics. Disconnection releases
manual input; it does not end an explicitly connected agent session.

## Atlas map data

Atlas map responses include a map-only SVG and `map_markers` (`ref`, `label`,
normalized `x`/`y`) for the returned visited nodes. `map_bounds` gives normalized
`left`/`right`/`top`/`bottom` bounds of retained visible path samples, nodes and the
current position. Desktop uses them for selection and fitting the view. These are
coordinates within the rendered SVG, derived from retained travel memory. They
do not expose unvisited geometry. The gameplay API's agent map presentation is
unchanged.

## Host artifacts and recordings

Runtime `status` includes `profile` with its ID and display name. Engine start
and agent connect accept an optional expected `profile` ID and reject a mismatch
without switching. Profile changes reset the active artifact registry and replay
index. Atlas, sessions, saves, knowledge and recording inventories are scoped to
the active profile. Profile mutation returns the updated catalog and `result`.
Deletion is permanent; an interactive client must request confirmation first.

The CLI materializes observation artifacts as local files. Recordings already
exist in the configured host folder, so completed recording responses return
those direct host paths without copying the MP4 again. The Desktop recording
browser can play/export them and open their host folder. The renderer obtains
media through the application bridge and range-capable artifact protocol.

Observation exports use a profile-specific host subdirectory. Recording artifacts
carry `X-Astra-Artifact-Relative-Path`, relative to the configured host recording
root, so the CLI can return files from the active profile's subfolder without
copying videos. `astrabridge recordings` lists host recordings across profiles, with local paths
and `profile_id` / `profile_name`, without starting a container. Desktop reads
the same host folder and can filter by selected profile.

Atlas is always served by the daemon. Viewing it does not issue a gameplay
observe/pause command. Offline/stored positions are marked historical, and no
navmesh or unvisited global geometry is exposed.

`GET /v1/runtime/gpus` lists devices visible in the container. Runtime configuration
accepts independent `graphics_gpu` and `encoding_gpu` selectors. See
[GPU selection](gpu-selection.md) for IDs, probes and fallback behavior.

Application-level `astrabridge status` also reports `currentVersion`,
`previousRuntime`, `updateRequired`, `updatePending` and `cleanupPending`.
These describe host management, not game state. `astrabridge update` recovers an
interrupted transaction before allowing another update attempt. The new Desktop
exports its bundled skill with `command: "astrabridge"`, the permanent launcher
path in `executable`, and `config` in `installation.json`. It has no profile
binding; agent connect uses the currently selected profile. Enable the launcher
with `astrabridge cli install` or Setup before exporting. `cli status` reports the
registered application/configuration, target availability and PATH readiness;
`cli uninstall` removes a matching registration. These host operations require
no running game or daemon.

Successful updates of the registered installation refresh the launcher atomically.
Opening an older Desktop or switching profiles does not rebind it. Existing skill
copies therefore remain usable after application replacement; re-export when the
instructions change. Legacy exports still use their executable plus explicit
`--config`, and should be replaced once to adopt the permanent command.

## Spectator timeline

Game command `comment` accepts `{ "text": "..." }` (1–4096 UTF-8 bytes).
It requires agent ownership but can run alongside an active action. It does
not call the engine or change input/pause state. No model-specific integration
is required; external chat is not automatically collected.

Runtime status/WS status includes `session`, `clocks` and a bounded `timeline`
of recent comment and action events. Actions have `action_id`, `operation`,
`state` (`active`, `finished`, `error`), and available result summary/feedback.
Completion means the command returned; its summary may still report blocked
movement. The Control entrypoint records short queries as well as long actions.

Each event has Unix `time`, session-relative `wall_seconds` (only while the
agent owns control), and `game_seconds` (accumulated engine simulation seconds).
The Lua adapter reports simulation time and pause state on changes and every
15 rendered frames. `game_active` uses world pause state, not recording/media
activity: menu audio may continue while simulation is paused. Wall time resumes
on reconnect in the same engine session. Both clocks reset with a new session.
Events during recording also carry `recording` and `recording_seconds`, derived
from MediaStream samples relative to the recorder's start sample.

The selected profile stores `sessions/<session>.timeline.jsonl`. Each recording
has `.context.json` (profile ID/name, session, start clocks) and `.events.jsonl`
sidecars; its filename starts with the sanitized profile name. Renaming/deleting
a profile does not rename/delete existing recordings. Desktop's **Export timeline**
exports the event sidecar. Commentary is not inserted into Atlas or knowledge.

Recording event streams also include a `snapshot` at position zero and periodic
`clock` samples. These do not consume the live message/action history. Desktop
indexes complete JSONL lines from the host recording folder and reconstructs
comments, active/completed actions and interpolated clocks at the playback time.
`replay` metadata includes `profile_subdirectory` so the host can associate the
current MP4 with its sidecar. No future event is shown in a rewound view.

## Startup and installation failures

Runtime status includes `starting` and `stopping`, separately from `running`. A process becomes
running only after its initial bridge handshake and window initialization.
Startup failures remain in `error` and are returned with an actionable message.
Stop cancels initialization before waiting for the normal lifecycle lock; an
uninitialized process is terminated without waiting for an unavailable Lua inbox.
Short `ping`, `quit` and `stop` time budgets are honored. During daemon shutdown,
event WebSockets close in the server's shutdown phase, before it waits for active
request handlers. Persistent recording finalization remains part of engine stop.

Desktop status reports missing managed volumes and interrupted removal. Setup
provides configuration reset and resource-scoped uninstall, independently of the
update/recovery path. These are host management operations, not gameplay commands.

## User-requested session termination

Desktop **Stop session** / `astrabridge stop` records a host-side `session_end`
with `reason: "user_requested_stop"` and a timestamp before stopping the runtime.
This remains available through `astrabridge status` and `astrabridge agent status`
after the container exits. A new explicit host start clears the marker; agent
connect alone cannot silently undo it.

The engine-stop Runtime API records the same reason before interrupting input.
An in-flight Game API command returns `error: "user_requested_stop"`,
`retryable: false` and `session_end`; `action_result` or `action_error` preserves
its available diagnostics. Later commands report the deliberate termination
instead of a generic missing connection. The event is written into session
history and the recording timeline before finalization. Unexpected process or
network failures without a user-stop marker keep their original error.

## Save before a user stop

Desktop **Stop session**, including the close-window choice, uses
`POST /v1/runtime/engine/prepare-stop` before the existing engine-stop operation.
Preparation interrupts input, releases agent/manual control and pauses the game.
It attempts a regular `Astra session end` save with the normal game restrictions,
and confirms the new save/checkpoint. The response contains `token` and `save`
(`status: saved`, `not_needed`, or `failed`, with the saved item or failure reason).
Repeated preparation returns the same result, avoiding duplicate saves.

Failed preparation keeps the engine, viewer and recorder open. Desktop asks
**Stop without saving** or **Cancel**. Cancellation calls
`POST /v1/runtime/engine/cancel-stop` with the preparation token; it clears the
pending stop while leaving the game paused and control released. Manual and agent
acquisition are blocked until that decision. The low-level engine-stop endpoint
remains available for lifecycle cleanup and an explicitly confirmed discard.

The host CLI `astrabridge stop` follows the same save-first path. When saving
cannot be confirmed it returns `save_before_stop_failed` with
`needs_confirmation: true`, without stopping the container. The host user can
choose `stop --without-save` or `stop --cancel`. Startup/no active game skips
saving. Update, uninstall and lower-level lifecycle cleanup retain their existing
backup/deletion semantics.
