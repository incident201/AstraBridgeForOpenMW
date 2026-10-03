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
copying videos. `astrabridge recordings` returns that profile's folder and list.

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
exports its bundled skill with executable/configuration paths and the active
profile's ID/name in `installation.json`;
re-export it after changing application versions, especially when the AppImage
filename changes. Existing exported copies are not rewritten automatically.
