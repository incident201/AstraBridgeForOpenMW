# Sessions, saves and recovery

Read this for connection issues, save/load, handoff or recovery. Commands follow
`astrabridge game` unless marked as application commands.

## Start or resume

Use application `astrabridge status` to check the runtime and selected profile,
then `astrabridge agent connect` to reserve control. Reuse your existing matching
connection. Do not disconnect another owner to take over. Report installation,
version or startup problems to the host user.

On context recovery, check game `status` and any outstanding `action-result`
before issuing another mutation. Once idle, read `knowledge brief`, obtain a
fresh `observe`, and inspect its image. Use `status --player` or an appropriate
`inspect` query to recover omitted character details. Follow the user's choice
of continuing, loading or starting anew; `saves` supplies fresh refs for the
intended slot.

Agent ownership persists between commands and while thinking. Application
`astrabridge agent disconnect` pauses the game and releases control for a human;
closing a terminal does not disconnect. The Desktop viewer can display past
footage, so use current observations and handles for game decisions.

Each selected Desktop profile has its own saves and memory. A new profile is
empty; explicit duplication copies saves and memory once. The host manages
profiles, imported saves and runtime updates. After reconnecting to another
profile, discard the previous profile's handles and assumptions and read the
new profile's `knowledge brief`. Changing profiles does not require re-exporting
the skill. An imported or developer save is an authorized starting point only
when the user requests that scenario.

If a command returns `user_requested_stop`, stop gameplay and report it. Do not
reconnect or restart automatically. Its `action_result` or `action_error`, when
present, describes the interrupted command. A new user request is required to
resume after a deliberate stop.

After an authorized runtime restart/update, reconnect and refresh transient
handles. If the configured executable or CLI command no longer works, ask the
host to repair it or provide an updated skill export.

## Saves and process lifecycle

| Syntax | Behavior |
|---|---|
| Application: `astrabridge start` | Start the runtime/game when authorized; preserve an already running game. |
| Application: `astrabridge agent connect` | Reserve agent control across calls; manual input is disabled until disconnect. |
| `new-game` | Start normal character creation; videos are skipped. Discards unsaved current progress. |
| `save "DESCRIPTION"` | Create a new slot when saving is allowed. Description: 1…160 UTF-8 bytes. Returns `saved` and `total_saves`. |
| `saves` | List slots with descriptions, player names and fresh refs. |
| `load SAVE_REF` | Load that slot. Unsaved progress is lost; refresh transient refs. |
| `stop` | Interrupt active input and pause. Does not save or quit. Read the interrupted command's result. |
| `autosave [--enabled/--no-enabled] [--interval S] [--slots N]` | Inspect/configure automatic saves. Defaults: enabled, 300 simulation seconds, three slots. Saves at legal action boundaries; preserves manual slots. |
| `finish-session --description "TEXT"` | Stop, attempt a save, finalize recording and close. Read `stages` and `closed`. If saving fails, the game stays open, but recording finalization is still attempted. |
| `action-result [REQUEST_ID] [--full]` | Retrieve a saved command result without executing it again; see [result recovery](information.md#recover-a-command-result). |
| Application: `astrabridge agent disconnect` | Stop active input, pause and release control. Does not save or stop recording/runtime. |
| Application: `astrabridge stop` | Attempt a save, then stop recording, game and container. Leave `save_before_stop_failed` to the host; do not add `--without-save` automatically. |
| Application: `astrabridge restart` | Restart runtime/game, normally to the menu. Does not save progress or resume recording automatically. Connect again afterward. |

Only one gameplay command can run at a time. During it, `status`, `stop` and
`action-result` remain available. `status --player` also requires the gameplay
controller. A `controller_busy_use_status_or_stop` error is not a failed game
action; wait or deliberately interrupt the active command.

Saving may be unavailable during character creation or a modal UI. Preserve the
paused game or reach a normal save opportunity; do not bypass the restriction.

## Recovery

| Signal | Next step |
|---|---|
| `stale_ref`, `stale_ui_ref`, `stale_observation` | Refresh the relevant query and choose from current data. |
| `view_unavailable`, `action_unavailable`, `save_unavailable` | Check tutorial, menu and body restrictions. |
| `ui_input_required` | Read the popup and choose its current enabled control. It can occur in `Gameplay`; check `ui.modal`. Closing it does not resume the interrupted action. |
| `ui_open`, `game_paused` | Inspect the actual UI and whether the previous action already happened before retrying. |
| `point_not_ground` | No movement started: that pixel did not resolve to a walking surface. Choose another visible surface or a fresh `ground` ref. |
| `blocked`, `no_path`, `path_end_out_of_reach`, `step_limit` | Inspect `summary`, actual motion, navigation diagnostics and the image. A time limit alone is not a reason to repeat with more time. |
| `target_lost`, `target_not_visible` | Reacquire visually; do not query hidden target positions. |
| `target_locked_unlock_first`, `locked_camera` | Switch to another visible actor with `lock` or use `unlock` before independent turning/navigation. |
| `spell_failed`, unavailable magic/ammunition | Read messages and own resources before choosing another attempt. |
| `levitation_ended`, `water_walking_ended` | Inspect support, height and water state before continuing. |
| Controller timeout or disconnection | Recover `action-result REQUEST_ID` and status. The mutation may have happened; do not automatically repeat it. |
| Missing prerequisites, managed storage, content files or required update | Report the error to the host user. Do not install, reset or reconfigure the runtime as a gameplay workaround. |

### Emergency actor placement recovery

`resetNPC --reason "Observed actor-placement malfunction"` is a last resort for
an observed actor-placement malfunction, such as a previously stationary travel
NPC drifting off its platform. First inspect the location and travel memory,
then save separately and close menus. Never use it for ordinary NPC obstruction,
combat, quest shortcuts or a failed route.

It returns eligible NPCs and creatures in all active cells to their original
positions. It does not resurrect actors or reset player stats. Refresh transient
handles with `observe` afterward and verify the intended interaction before
saving the recovered state.

If the public interface cannot perform an essential operation, report the
command, result and current observation. Gameplay permission does not authorize
changing the interface or reading its internals.
