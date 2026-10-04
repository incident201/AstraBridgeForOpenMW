# Sessions, saves and recovery

Read this for connection/profile issues, save/load, handoff or recovery. Commands follow `astrabridge game` unless marked as application commands.

## Reproducible environment

The user installs the matching Desktop/runtime release. Before a playtest,
retain `astrabridge version` and `astrabridge status`: these application commands
report the release/image identity and running environment. Session and recording
environment sidecars are saved automatically. Version and image metadata are
public environment information, not game-state data.

## Start or resume

1. Run `astrabridge status`. If `updateRequired` or `updatePending` is true, or the managed container is missing, ask the host user to finish setup/update/recovery first. Otherwise run `astrabridge agent connect`. The connection uses the currently selected Desktop profile and reserves control across subsequent CLI calls. Check the returned profile to identify this playthrough. If already connected, use that connection; do not end another owner's session to take over. No host display or manual container commands are needed.
2. When resuming context, first check `status` and any outstanding `action-result`; once idle, use `knowledge brief` as described in [memory](memory.md#resume-after-context-loss). Run `astrabridge game observe` and open the returned local `screenshot` with the image-viewing tool. A path in JSON is not itself an image presented to the model.
3. Follow the user's choice of continuing, loading, or starting a new game. Use `saves` to obtain a fresh save handle before `load`; do not load an arbitrary latest slot or a developer fixture.
4. Use `status --player` for a fast character summary. It does not open menus, capture an image, or invalidate item/spell handles.

If a command returns `error: "user_requested_stop"` with `session_end`, the host
user deliberately ended the session. Stop gameplay and report that termination;
do not reconnect or restart automatically. Any `action_result`/`action_error`
contains the interrupted command's available diagnostics. `astrabridge status`
and `astrabridge agent status` retain the stop reason after the container exits.
A new explicit host **Start game** / `astrabridge start` clears it before the
agent can connect again.

The agent session remains connected between commands and during long reasoning
pauses. The Desktop viewer can stay open, but manual input is disabled while
the agent owns control. Use `astrabridge agent disconnect` when handing control
back; this stops active input and leaves the game paused. Closing a terminal does not disconnect the agent. When Desktop closes, its
**Keep running** choice leaves the agent and recording session active; **Stop
session** attempts a game save and then finalizes recording and shuts down. If
saving is unavailable, the host chooses whether to stop without saving or cancel. If the user deliberately stops or removes the runtime, do not
restart it behind their back.

The Desktop timeline can show a paused or earlier recording while the game keeps
running. `game observe` and action responses always describe the current game,
independently of the viewer. Use their returned screenshots and current handles
for decisions, not a past frame displayed in Desktop.

Each Desktop profile has separate saves, Atlas, recognized objects, notes and
session history. Profile management requires the game to be stopped. A newly
created profile has no inherited game knowledge. **Duplicate profile** deliberately
copies existing saves and memory once; subsequent changes are independent.
Use only the active profile's memory and the user's intended playthrough. After
reconnecting to a different profile, discard old handles and assumptions and
read that profile's `knowledge brief`. Switching or renaming profiles needs no
skill re-export. Ignore a legacy `profile` field in an older `installation.json`;
it is not a connection requirement. An explicit application `--profile ID` is
an optional mismatch guard, not a profile switch.

After an authorized runtime update/restart/recreation, connect again, observe and
refresh all transient handles. Saves, Atlas and knowledge survive a container
replacement. With the permanent CLI enabled, a successful runtime update switches
the launcher to the matching application. Re-export the skill when its instructions
change; changing an AppImage/EXE filename alone does not require a new export.
Check actual `astrabridge version` and `astrabridge status` values to diagnose a
mismatch, rather than comparing filenames in two exports. If the target is missing
or incompatible, ask the host to repair the CLI command in Setup. Do not guess a
binary, edit configuration, enter a container or apply an update as a gameplay
workaround. Legacy exports with direct application paths should be replaced once
with a complete new export after the host enables the permanent command.

## Saves and process lifecycle

| Syntax | Behavior |
|---|---|
| Application: `astrabridge start` | Start the persistent runtime and game; preserve an already running game. Watch it through Desktop. |
| Application: `astrabridge agent connect` | Reserve agent control across CLI calls. No inactivity timeout; manual input is disabled until disconnect. |
| `new-game` | Start the normal new-game/character-creation flow; all videos are skipped automatically. Discards unsaved current progress. |
| `save "DESCRIPTION"` | Create a new save slot, description 1…160 UTF-8 bytes. Returns `saved` and `total_saves`. Only when the game permits saving. |
| `saves` | List slots with descriptions, player names and fresh refs. |
| `load SAVE_REF` | Load that slot; unsaved progress is lost and transient refs must be refreshed. |
| `stop` | Interrupt immediately through an independent control channel, clear inputs and pause. The interrupted command retains its elapsed time/result. Does not save or quit. |
| Application: `astrabridge restart` | Finalize recording and restart the persistent runtime, normally to the menu. Does not autosave, select a save or restart recording. Connect again afterward. |
| `autosave [--enabled/--no-enabled] [--interval S] [--slots N]` | Configure or inspect the persistent autosave ring. Default: enabled, 300 simulation seconds, three slots. Saves only at a legal paused command boundary; long actions are not forcibly paused. Failed saves are reported/deferred. Manual slots are preserved. |
| `finish-session --description "TEXT"` | Interrupt the active command, save, finalize recording and close. Reports each stage; keeps the game open if saving or recording finalization fails. |
| `action-result [REQUEST_ID] [--full]` | Retrieve a durable command receipt; see [information](information.md#recover-a-command-result). |
| Application: `astrabridge agent disconnect` | Interrupt an active action, clear held input, pause and release control. Does not save or stop the runtime. |
| Application: `astrabridge stop` | Try to save, then close game/recording and stop the persistent container. On `save_before_stop_failed`, leave the decision to the host user; never retry with `--without-save` automatically. |

One gameplay command owns the controller at a time. While it runs, use `status` or `stop`; another gameplay command returns `controller_busy_use_status_or_stop`. `status --player` reads the engine and also needs the gameplay owner. For the complete save/record-stop/close request, use `finish-session`; use individual operations when the user requests only part of that lifecycle.

If saving is unavailable during the tutorial or a modal UI, do not bypass it. Preserve the paused session or reach a normal save opportunity. Do not treat a developer/test slot as a legitimate gameplay start unless the user explicitly requests that scenario.

## Recovery

Application startup can return `prerequisites_missing` with `prerequisites.checks`
listing missing host components and remedies. Refer the host user to
**Setup → System requirements**. Gameplay commands cannot install or repair
Podman, GPU drivers or CDI; do not change host configuration as a gameplay workaround.

| Signal | Next step |
|---|---|
| `stale_ref`, `stale_ui_ref`, `stale_observation` | Refresh the relevant query; choose again from current data. |
| `view_unavailable`, `action_unavailable`, `save_unavailable` | Check tutorial/menu/body restrictions. Do not bypass them. |
| `ui_input_required` | An input-requiring popup interrupted the action, even if `ui_mode` is `Gameplay`. Movement/held input is stopped; the observation includes `ui.modal`, message and controls. Read it, `ui`/`choose` its enabled button, then decide on a new action using actual movement/side effects. No automatic resume. |
| `ui_open`, `game_paused`, a modal | Read/handle the actual UI; determine whether the interrupted action already executed. Starting new movement while a modal is open is rejected with `ui_open`. |
| `point_not_ground` | No movement started: the selected pixel did not resolve to a walking surface. Choose a clear tread/deck pixel or a fresh `ground` ref; see [stairs and bridges](navigation.md#pick-an-operation). This does not prove the route is blocked. |
| `blocked`, `no_path`, `path_end_out_of_reach`, `step_limit` | Inspect actual movement, local geometry and the screenshot. Select another reachable point or shorter action. |
| `target_lost`, `target_not_visible` | Reacquire visually. Do not query hidden target positions. |
| `target_locked_unlock_first`, `locked_camera` | Inspect the lock; explicitly `lock` a different visible actor or `unlock` before independent turning/navigation. |
| `spell_failed`, unavailable magic/ammunition | Read messages, effects and own resources; change the gameplay decision. |
| `levitation_ended`, `water_walking_ended` | Effect-dependent route stopped. Inspect support/height/water state before continuing. |
| Application status reports `updateRequired`, `updatePending`, or a missing container | Refer the host user to Setup. Image updates, recovery and container recreation are host management tasks. Resume authorized gameplay with the matching exported skill, reconnect and obtain fresh observations/handles. |
| Controller timeout/disconnection/uncertain state | Do not automatically replay a mutation. Query `action-result REQUEST_ID` and status after reconnecting, stop if needed, then decide whether restart/load is necessary. |

### Emergency actor placement recovery

`resetNPC --reason "Observed actor-placement malfunction"` runs the engine's RA/ResetActors operation. It is a last resort for a confirmed or strongly evidenced malfunction, such as a previously observed stationary travel NPC drifting off its platform. First inspect the location and existing travel memory, then save to a separate slot. Close menus before calling it. It is never automatic and must not be used to bypass enemies, quests, ordinary NPC obstruction or a failed path.

Despite its name, the engine operation affects eligible **NPCs and creatures in all active cells**, returning them to their original positions/orientations; actors moved in from another cell and actors without a content-file origin are excluded by the engine. It does not resurrect actors or reset player stats. The reason is logged. Transient actor/item/UI/navigation handles are invalidated; the learned atlas remains. Observe again and verify that the intended NPC and interaction are restored before saving the recovered state. YAIAF prevents idle-animation drift going forward; it does not repair positions already stored in an old save.

If the public interface cannot perform an essential operation, report the command, response and current observation to the user/developer. Gameplay permission does not authorize modifying the interface.

### Host GPU configuration

`astrabridge gpus` lists available runtime devices. The host user can select
rendering and encoding devices in Desktop Settings or with `astrabridge config`.
`astrabridge start --gpu GPU_ID` and `restart --gpu GPU_ID` override rendering
for that start. `game record-start`, `game record-status` and `game record-stop` use the configured
encoder automatically: the runtime probes
the configured encoder and records the result in metadata. If an explicitly
selected device is unavailable, report the error to the host user.

If startup reports a missing managed store or a content load-order/dependency
error, report it to the host user. Setup can recover or reset installation state;
Game data settings control selected files and their order. Do not reset, uninstall
or replace a playthrough as a gameplay recovery step. A `starting` runtime is not
a ready game; wait for startup to complete or let the host stop the attempt.
