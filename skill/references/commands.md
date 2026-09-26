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
| `passage_…` | `observe` → `terrain.passages[].ref` | `go` | Short-lived local sample; refresh after moving. |
| `ground_…` | `ground` → `ground_targets[].ref` | `go`, `walk --ref` | Short-lived visible-point sample; use promptly without moving first. |
| `node_…` | `atlas` / observation → `exploration.nodes[].ref` | `revisit` | Persistent recorded node in this playthrough and space. Check `can_revisit` and `revisit_source`. |
| `place_…` | `remember`, `recall` | `return-to`, `connect` | A semantic note; returning requires a valid recorded motor marker. |
| `save_…` | `saves` → `saves[].ref` | `load` | Fetch a fresh save listing immediately before loading. |

Do not pass an NPC ref to `go`, a map label such as `A4` to `revisit`, or an inventory `item_…` ref to `choose`. Those are different handle types. After load/new-game/restart, discard transient refs. `status --player` does not invalidate item/spell handles.

## Information commands

| Syntax | Result / purpose |
|---|---|
| `status` | Controller/game process state and recording state; **not** character stats. |
| `status --player` | Fast character summary, no menu or screenshot. |
| `inspect character` | Same character information. |
| `observe` | Fresh screenshot-bearing observation; world remains paused. |
| `inspect stats` | Detailed own attributes and skills. |
| `inspect inventory` | Owned items, refs, counts, equipment state, carried weight/capacity. |
| `inspect spells` | Known spells/powers, refs, effects, cost, success chance, selection and availability. |
| `inspect effects` | Active effects and their sources. |
| `inspect combat` | Own selected weapon/ammunition/tool and selected spell/enchantment. |
| `inspect journal --page N` | Journal entries already received; zero-based pages. |
| `inspect conversations` | Topics already known by the character. |
| `inspect conversations --topic "EXACT_TOPIC" --page N` | Recorded dialogue for that known topic; not an interaction with an NPC. |
| `ui` | Current structured UI, including visible item tooltips. |

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

## Saves and process lifecycle

| Syntax | Behavior |
|---|---|
| `start` | Start a normal window with sound in the graphical session; preserve an already running controller. |
| `start --display DISPLAY --recordings-dir PATH` | Optional X display/recording-directory overrides. Use the user's configured environment, not a new virtual display. |
| `new-game` | Start the actual introduction/character-creation flow. Discards unsaved current progress. |
| `save "DESCRIPTION"` | Create a new save slot, description 1…160 UTF-8 bytes. Only when the game permits saving. |
| `saves` | List slots with descriptions, player names and fresh refs. |
| `load SAVE_REF` | Load that slot; unsaved progress is lost and transient refs must be refreshed. |
| `stop` | Clear active controls and request a pause. Does not save or quit. |
| `restart` | Stop/relaunch the game, normally to the menu. Does not autosave. |
| `restart --load-latest` | Load the newest available slot after restarting; use only if that is actually desired. |
| `shutdown` | Close controller/game and recording. Does not autosave. |

If saving is unavailable during the tutorial or a modal UI, do not bypass it. Preserve the paused session or reach a normal save opportunity. Do not treat a developer/test slot as a legitimate gameplay start unless the user explicitly requests that scenario.

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

If the public interface cannot perform an essential operation, report the command, response and current observation to the user/developer. Gameplay permission does not authorize modifying the interface.
