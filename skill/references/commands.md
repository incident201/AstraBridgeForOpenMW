# Public command reference

Contents: [calling convention](#calling-convention), [responses](#read-responses-correctly), [handles](#handles-and-freshness), [information](#information-commands), [UI](#menus-and-dialogue), [lifecycle](#saves-and-process-lifecycle), [recording](#recording), [recovery](#recovery).

Movement and maps: [navigation.md](navigation.md). Combat and tools: [combat.md](combat.md).

## Calling convention

Every command below is prefixed with `./astra` and runs from the configured harness directory. Use `./astra COMMAND --help` for parser help; it does not run an action. Do not start the internal `serve` process manually.

Notation:

- `ACTOR_REF`, `UI_REF`, `ITEM_REF`, `NODE_REF`, etc. mean an actual opaque `ref` returned by the matching query. Replace them before execution.
- `OBS` means the integer `observation` from the latest screenshot-bearing observation, not a frame number or filename.
- Names and captions must match the game's language exactly. English documentation does **not** make a Russian UI accept English labels.
- JSON arguments use JSON booleans (`true`/`false`) and double-quoted keys. Shell examples wrap the whole JSON in single quotes.
- Examples are individual decisions, not scripts to execute blindly. Inspect each result before its dependent step.

The CLI returns `{ "ok": true, "result": ... }` or `{ "ok": false, "error": "..." }`. A rejected request exits with a nonzero status. An `ok:true` action may still be blocked, interrupted, partial, or unsuccessful in the game.

## Read responses correctly

**Read/query:** `observe` returns the observation directly inside `result`. `status --player` returns character data there. `inspect inventory` returns `result.items`, `carried_weight`, and `capacity`. `ui` returns `result.elements`.

**Most actions:** `result` contains `action`, `feedback`, and a new `observation` object. Some lifecycle/memory commands return other shapes. Do not assume every result has a nested observation.

Illustrative subset of a movement response:

```json
{
  "ok": true,
  "result": {
    "action": {"reason": "arrived", "motion": {"moved_m": 2.9}},
    "feedback": {"status": "succeeded", "events": [], "reason": "arrived"},
    "observation": {
      "observation": 43,
      "ui_mode": "Gameplay",
      "screenshot": "/path/to/runtime/screenshots/example.png"
    }
  }
}
```

In a real observation, use:

| Field | Meaning / action |
|---|---|
| `screenshot` | Current game-window PNG. Open it explicitly to see it. |
| `observation` | Screenshot/observation number for coordinate-based UI operations. |
| `ui_mode`, `ui.modal`, `ui.elements` | Which menu is open, whether a modal blocks it, and actual controls. Tutorial popups can still report `Gameplay`. |
| `scene.objects` | Visible actors, doors, items, containers; refs, names, relative geometry, screen bounds and reach. |
| `body` | Stance, selected gear/magic, animation, support/swimming state, death and mobility effects. |
| `stats`, `effects`, `combat` | Own resources, active effects, selected attack/cast capabilities. |
| `orientation` | Heading, pitch, FOV and camera mode. |
| `terrain`, `local_map`, `exploration` | Local navigation data and recorded travel memory; see navigation reference. |
| `messages` | Recent observed game messages; not necessarily all new in this response. Prefer `feedback.events` for changes. |

`action.motion` reports what actually happened: forward/sideways/vertical movement, distance, turning, and location change. `action.navigation` can explain remaining distance, tolerances and partial paths.

`submitted` means the request was sent, not that an item was equipped, purchased or a door opened. A spell attempt can have `action.reason=completed` (animation finished) but `feedback.status=failed`, `feedback.reason=spell_failed`, and `cast_outcome=failed`. Verify the relevant effect, inventory, menu, HUD, or message.

## Handles and freshness

| Value | Obtain from | Use with | Refresh rule |
|---|---|---|---|
| `visible_…` | `observe` → `scene.objects[].ref` | `focus`, `approach`, `interact`; actor refs also `lock`, `strike`, `cast`, `chain` | Targets must remain valid/visible. Reobserve after movement or target loss. A remembered actor is not permission to track it through walls. |
| `item_…` | `inspect inventory` → `items[].ref` | `use-item`, `select-enchanted` | Inventory/spell queries share an ephemeral handle table. Either query replaces that table; many actions invalidate it too. Obtain the needed ref immediately before use. |
| `spell_…` | `inspect spells` → `spells[].ref` | `select-spell` | Same rule as items. Selection remains after its handle expires. |
| `ui_…` | `ui` → `elements[].ref`, or observation's `ui.elements` | `choose`, `edit`, `adjust`, `hover` | Bound to the current UI revision. Refresh after a UI change. |
| `document_…` | `ui.document.ref` or `read` | `read --ref` | Valid only for that opened book/scroll instance. Refresh after reopening or loading. |
| `passage_…` | `observe` → `terrain.passages[].ref` | `go` | Short-lived local sample; refresh after moving. |
| `ground_…` | `ground` → `ground_targets[].ref` | `go`, `walk --ref` | Short-lived visible-point sample; use promptly without moving first. |
| `node_…` | `atlas` / observation → `exploration.nodes[].ref` | `revisit` | Persistent recorded node in this playthrough and space. Check `can_revisit` and `revisit_source`. |
| `place_…` | `remember`, `recall` | `return-to`, `connect` | A semantic note linked to its persistent atlas node; legacy unlinked notes need a valid motor marker. |
| `save_…` | `saves` → `saves[].ref` | `load` | Fetch a fresh save listing immediately before loading. |

Do not pass an NPC ref to `go` or an inventory `item_…` ref to `choose`. Prefer persistent node refs; unique remembered names and labels from the current atlas also resolve. Those are different handle types. After load/new-game/restart, discard transient refs. `status --player` does not invalidate item/spell handles.

## Information commands

| Syntax | Result / purpose |
|---|---|
| `status` | Process/recording state and `active_action` with live phase, elapsed time and navigation; available during a long action. |
| `status --player` | Fast character summary, no menu or screenshot. |
| `inspect character` | Same character information. |
| `observe [--full] [--no-screenshot] [--map]` | Compact fresh observation with screenshot by default; full adds detailed sensors/effects/combat. Map files are opt-in. |
| `inspect stats` | Detailed own attributes and skills. |
| `inspect inventory` | Owned items, refs, counts, equipment state, carried weight/capacity. |
| `inspect spells` | Known spells/powers, refs, effects, cost, success chance, selection and availability. |
| `inspect effects` | Active effects and their sources. |
| `inspect combat` | Own selected weapon/ammunition/tool and selected spell/enchantment. |
| `inspect journal --page N` | Journal entries already received; zero-based pages. |
| `inspect conversations` | Topics already known by the character. |
| `inspect conversations --topic "EXACT_TOPIC" --page N` | Recorded dialogue for that known topic; not an interaction with an NPC. |
| `ui` | Current structured UI, including visible item tooltips. |
| `read [--ref DOCUMENT_REF] [--offset N] [--limit N]` | Text of the currently open book/scroll. Default 4000 characters, maximum 8000 per chunk; no page turning or scrolling required. |
| `read --all` / `read --search "TEXT"` | Assemble the opened document internally, or return matching passages with Unicode offsets. |

Character summary includes identity, sign, level, health/magicka/fatigue, eight attributes, skills and progress, weight/capacity, gold, bounty, reputation, equipment/magic and active effects. Effects provide name/source, description, `harmful`, strength where applicable, affected attribute/skill, total/remaining duration or `permanent`. `from_equipment` marks an effect tied to equipped gear.

`body.levitation`, `water_walking`, `water_breathing`, and `slow_fall` mean the effect is active. They do not prove that the character is airborne, on the water surface, or safe from drowning. Check `on_ground`, `swimming`, `submerged` and observed movement.

Reading inventory does not open the inventory UI. `use-item` is for **owned** items; world pickups need `interact`. For fuller item descriptions, open Inventory and inspect its visible `role:item` elements; undiscovered ingredient effects remain unknown.

## Menus and dialogue

| Syntax | Arguments and behavior |
|---|---|
| `trigger NAME` | Exact allowed names: `Activate`, `ToggleWeapon`, `ToggleSpell`, `Jump`, `Inventory`, `Journal`, `GameMenu`, `Rest`. Toggle names toggle state; check current stance/menu first. |
| `map` | Open the game's Map window; this is distinct from `atlas`. |
| `choose UI_REF` | Invoke an enabled visible control. |
| `choose "EXACT_CAPTION"` | Resolve a current caption. Prefer a ref for ambiguity; same-caption buttons are preferred over other control types. |
| `edit UI_REF "TEXT"` | Replace a visible input's contents, up to 1000 characters. It does not press its confirmation button. |
| `adjust UI_REF N` | Set a slider to integer position N, within its reported `slider_max`. This is a position, not an assumed percentage. |
| `hover UI_REF` | Move the cursor onto a current UI element and observe its normal tooltip. Requires an open UI. |
| `scroll N --observation OBS` | Scroll under the native UI cursor: −10…10 integer steps, negative = down. Hover the intended region first. |
| `click X Y --button B --observation OBS` | Window-relative pixels from the current screenshot; B=1/2/3 (left/middle/right), default 1. |
| `key KEY --observation OBS` | Allowed: `escape`, `enter`, `tab`, `space`, `up`, `down`, `left`, `right`, `backspace`, `delete`, `pageup`, `pagedown`. No arbitrary keys/chords. |
| `text "TEXT" --observation OBS` | Type 1…160 characters, no control characters, into the currently focused UI field. Prefer `edit` for identified inputs. |

Use named gameplay commands instead of raw clicks/keys for movement. For mouse/keyboard fallbacks, obtain a current observation first; another `observe` makes its earlier number stale. Structured `choose/edit/adjust/hover` use refs and **do not take** `--observation`.

UI roles: `button`, `link`, `list_item`, `input`, `slider`, `item`, `item_slot`, `drop_target`, `text`. Respect `enabled` and modals. Check `selected` after choosing a list row. In dialogue, all currently available sidebar topics/services are exposed in `ui.dialogue.topics` and `ui.elements`, including entries outside the viewport. Use `choose` directly; scrolling is unnecessary. `ui.dialogue.text` and `ui.text` contain the complete already displayed conversation history, never responses to unselected topics. `screen_visible:false` entries have no `rect` and cannot be hovered or clicked by coordinates, but can be chosen by ref. Other lists still expose their rendered rows. Close tutorial messages through their actual controls before retrying an interaction that did not execute.

**Dialogue:** approach/interact with a visible NPC → inspect `ui` → choose an actual topic/reply ref → read the new text → choose the game's farewell control when finished. Do not assume the window closed just because a reply was selected.

**Trading/containers:** inspect `panel` to distinguish `inventory`, `merchant`, and `container`. Choosing an item may open a quantity dialog or begin a drag. Resolve the actual dialog, then choose the destination `drop_target` if a drag is active. `pending_trade` means a proposal; use the merchant's real confirmation button and verify ownership/gold afterward. Closed-container contents are not exposed.

**Spellmaking, enchanting, alchemy, training, rest, level-up and character creation:** there are no separate high-level service commands. Use these same UI operations and the controls actually displayed. For example, rest opens via `trigger Rest`; then inspect its slider/buttons instead of assuming keyboard shortcuts or a particular caption.

### Books, scrolls and manual repair

Open an owned book with `use-item`, or a book in the world with `interact`. `ui.document` reports its title, kind, ref and total character count. Use `read --all` for the whole text or `read --search "TEXT"` for excerpts with offsets. For bounded replies, call `read` and continue with `read --ref DOCUMENT_REF --offset NEXT_OFFSET` until `eof:true`. Offsets count Unicode characters, not UTF-8 bytes. The text covers the whole opened document; observations carry metadata only, so long books do not overflow replies. The ref also works after turning pages. Closing/reopening the book invalidates it. `document_not_open` means no book/scroll is open; `stale_document_ref` requires a new query. Images remain available in the screenshot.

Use an owned repair hammer to open Repair. `ui.elements` includes the actual repairable rows as `role:item`, `panel:repair`, with `condition_current`, `condition_max` and the normal tooltip. Rows outside the viewport can be chosen semantically. Choosing one performs **one normal repair attempt**, consuming tool use and applying the game's skill/RNG rules. Refresh the UI after every attempt; failure is possible, and fully repaired items disappear. The `repair tool: …` slot shows the selected hammer and opens the game's tool selector when chosen. `repair "EXACT_ITEM_NAME" --attempts N --condition-pct P` repeats these normal attempts with fresh refs, stopping at the requested percentage, exhausted attempts, a changed menu, ambiguity or cancellation. Defaults are one attempt and 100%. Each attempt reports before/after condition when the row remains; fully repaired rows disappear. Identically named items require manual selection with `choose`; the helper never guesses.

## Saves and process lifecycle

| Syntax | Behavior |
|---|---|
| `start` | Start a normal window with sound in the graphical session; preserve an already running controller. |
| `start --display DISPLAY --recordings-dir PATH` | Optional X display/recording-directory overrides. Use the user's configured environment, not a new virtual display. |
| `new-game` | Start the actual introduction/character-creation flow. Discards unsaved current progress. |
| `save "DESCRIPTION"` | Create a new save slot, description 1…160 UTF-8 bytes. Only when the game permits saving. |
| `saves` | List slots with descriptions, player names and fresh refs. |
| `load SAVE_REF` | Load that slot; unsaved progress is lost and transient refs must be refreshed. |
| `stop` | Interrupt immediately through an independent control channel, clear inputs and pause. The interrupted command retains its elapsed time/result. Does not save or quit. |
| `restart` | Stop/relaunch the game, normally to the menu. Does not autosave. |
| `restart --load-latest` | Load the newest available slot after restarting; use only if that is actually desired. |
| `shutdown` | Close controller/game and recording. Does not autosave. |

One gameplay command owns the controller at a time. While it runs, use `status` or `stop`; another gameplay command returns `controller_busy_use_status_or_stop`. `status --player` reads the engine and also needs the gameplay owner. After `stop`, follow the user's requested save/record-stop/shutdown sequence.

If saving is unavailable during the tutorial or a modal UI, do not bypass it. Preserve the paused session or reach a normal save opportunity. Do not treat a developer/test slot as a legitimate gameplay start unless the user explicitly requests that scenario.

## Conditional waits and sequences

`wait-until fatigue --percent 100 --seconds 30` advances simulation until fatigue reaches the percentage. Other conditions are `animation` (idle/recovered), `passage --bearing-deg B --meters M` (locally clear, M≤6), and `ui --ui-mode MODE`. It returns `condition_met` or `condition_timeout`, with ordinary interruption on death, unexpected UI/location or `stop`. Waiting consumes game time.

`sequence` composes ordinary public actions, resolving owned item/spell names against fresh inventory/spell handles:

```sh
./astra sequence '{"actions":[{"op":"use_item","name":"EXACT_OWNED_ITEM_NAME"},{"op":"wait_until","condition":"animation","seconds":5},{"op":"act","move":1,"seconds":3}],"max_seconds":15,"stop_on_damage":true,"stop_health_pct":35}'
```

Steps use API names with underscores: `act`, `look`, `go`, `walk`, `revisit`, `return_to`, `approach`, `interact`, `move_local`, `use_item`, `select_spell`, `select_enchanted`, `cast`, `strike`, `chain`, `wait_until`, `trigger`, `choose`, `lock`, `unlock`. Each step contains `op` plus that operation's normal fields. Item/spell selection also accepts an exact unique `name`. Every step is validated before execution; stale UI/scene refs still require stopping and reacquiring. Do not preselect replies from dialogue that has not been opened/read.

Default total simulation budget is 60 seconds; it has no fixed upper cap. Remaining time limits timed steps; atomic UI operations, finite turns and individual casts/strikes finish normally and can overrun the remaining budget. A combat `chain` uses its own continuous motor deadline. `stop_on_damage` defaults to true and `stop_health_pct` to 0 (disabled). Interruptions stop the remaining sequence; already consumed items are not replayed. Only the final observation captures a screenshot. Sequence boundaries retain ordinary brief command pauses; use a combat `chain` for continuous concurrent movement/casting, and `interact --approach` for uninterrupted approach/aim/activation.

## Screenshot storage

Ordinary screenshots are a rolling cache: the latest 128 by default, configurable via `screenshot_keep` (integer ≥8) in local `local-settings.json`. Screenshots explicitly attached by `remember` are protected; those notes retain up to six views each. Old automatic atlas links are returned only while their image exists. SQLite paths, nodes, names and door links survive cache cleanup. Use the screenshots to inspect appearances and obstacles; the atlas stores travel knowledge, not a substitute rendered view.

Map SVG/PNG files are generated only with `observe --map` or `atlas --map`. The atlas map reuses `atlas-current.svg/png`; other generated maps have an eight-file cache. User-named files and recordings are not pruned.

## Recording

`record-start` starts a new H.264 MP4 in the configured directory. `record-status` returns its `path`, frames/duration, `recording`, `capturing`, backend and any `error`. `record-stop` finalizes it.

The timeline includes active gameplay and UI work, excludes thinking pauses, and has no audio. Output is 60 fps H.264 (CRF 18), sampled from completed OpenMW back-buffer frames before buffer swap. Capture and encoding run separately; the video uses a uniform 1/60-second timeline. No file-size limit is imposed. Keep the window size stable while recording.

`rendered_frames`, `repeated_frames`, `ring_dropped_frames`, `encoder_queue_peak` and `frame_interval_ms` expose actual capture performance. Engine stalls, including loading, can still require repeated frames to preserve duration. Check these counters rather than trusting nominal FPS. The render hook requires the matching patched engine; an older binary reports `engine_frame_unavailable_rebuild_engine`. Screenshots also use completed frames (`capture_sync: render_complete`) when available. There is no desktop/compositor readback in this recording backend. `video_window_resized` requires a new recording. Do not claim a recording succeeded without checking its final status.

## Recovery

| Signal | Next step |
|---|---|
| `stale_ref`, `stale_ui_ref`, `stale_observation` | Refresh the relevant query; choose again from current data. |
| `view_unavailable`, `action_unavailable`, `save_unavailable` | Check tutorial/menu/body restrictions. Do not bypass them. |
| `ui_open`, `game_paused`, a modal | Read/handle the actual UI; determine whether the interrupted action already executed. |
| `blocked`, `no_path`, `path_end_out_of_reach`, `step_limit` | Inspect actual movement, local geometry and the screenshot. Select another reachable point or shorter action. |
| `target_lost`, `target_not_visible` | Reacquire visually. Do not query hidden target positions. |
| `target_locked_unlock_first`, `locked_camera` | Inspect the lock; explicitly `lock` a different visible actor or `unlock` before independent turning/navigation. |
| `spell_failed`, unavailable magic/ammunition | Read messages, effects and own resources; change the gameplay decision. |
| `levitation_ended`, `water_walking_ended` | Effect-dependent route stopped. Inspect support/height/water state before continuing. |
| Controller timeout/disconnection/uncertain state | Do not automatically replay a mutation. Query status/observe after reconnecting, stop if needed, then decide whether restart/load is necessary. |

### Emergency actor placement recovery

`resetNPC --reason "Observed actor-placement malfunction"` runs the engine's RA/ResetActors operation. It is a last resort for a confirmed or strongly evidenced malfunction, such as a previously observed stationary travel NPC drifting off its platform. First inspect the location and existing travel memory, then save to a separate slot. Close menus before calling it. It is never automatic and must not be used to bypass enemies, quests, ordinary NPC obstruction or a failed path.

Despite its name, the engine operation affects eligible **NPCs and creatures in all active cells**, returning them to their original positions/orientations; actors moved in from another cell and actors without a content-file origin are excluded by the engine. It does not resurrect actors or reset player stats. The reason is logged. Transient actor/item/UI/navigation handles are invalidated; the learned atlas remains. Observe again and verify that the intended NPC and interaction are restored before saving the recovered state. YAIAF prevents idle-animation drift going forward; it does not repair positions already stored in an old save.

If the public interface cannot perform an essential operation, report the command, response and current observation to the user/developer. Gameplay permission does not authorize modifying the interface.
