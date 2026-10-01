# Runtime API and application interfaces

Desktop and its CLI mode share Application Core, connection configuration and
the same API client. Gameplay commands are grouped under `astrabridge game`.
Their options come from the Python command catalog, exported into the Desktop
package during its build.

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
| `POST /v1/agent/connect` | Acquire agent ownership; accepts a display `name`. |
| `POST /v1/agent/disconnect` | Stop held input and release the authenticated agent session. |
| `GET /v1/agent/status` | Public ownership state, without its credential. |
| `POST /v1/runtime/agent/end` | Deliberate user termination of the current owner. |
| `GET /v1/game/schema` | Public command catalog. |
| `POST /v1/game/command` | Execute `{ "op": "...", "args": {...} }` as the connected agent. |
| `POST /v1/runtime/recording/{start,stop,status}` | Recording management. |
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

## WebSocket input

The application sends `manual.acquire`, `manual.release`, or an `input` envelope
with an `event`. Input event types are `key`, `button`, `pointer`, `relative`,
`wheel`, `text` and `release`. Absolute pointer coordinates are normalized to the
displayed game area; relative movements are bounded pixel deltas. Key events use
DOM physical key codes. Only the owning manual connection can submit input.

Server events include `status`, `input.owner` and `error`. Status updates carry
action progress and separate game/capture/viewer metrics. Disconnection releases
manual input; it does not end an explicitly connected agent session.

## Host artifacts and recordings

The CLI materializes observation artifacts as local files. Recordings already
exist in the configured host folder, so completed recording responses return
those direct host paths without copying the MP4 again. The Desktop recording
browser can play/export them and open their host folder. The renderer obtains
media through the application bridge and range-capable artifact protocol.

Atlas is always served by the daemon. Viewing it does not issue a gameplay
observe/pause command. Offline/stored positions are marked historical, and no
navmesh or unvisited global geometry is exposed.

`GET /v1/runtime/gpus` lists devices visible in the container. Runtime configuration
accepts independent `graphics_gpu` and `encoding_gpu` selectors. See
[GPU selection](gpu-selection.md) for IDs, probes and fallback behavior.
