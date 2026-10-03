# Command conventions and responses

Use this reference for argument syntax, response fields and handle freshness. Read [UI](ui.md), [session/save/recovery](session.md), [sequences](sequences.md), [recording](recording.md), [information](information.md), [memory](memory.md), [navigation](navigation.md), or [combat](combat.md) only when relevant.

## Calling convention

Every gameplay command below follows `astrabridge game`, using the executable
and `--config` path from the exported skill's `installation.json`.
Use `astrabridge game COMMAND --help` for parser help; it does not run an action.
For connecting, profile mismatches, host requirements and save/load, see [session.md](session.md).

Notation:

- `ACTOR_REF`, `UI_REF`, `ITEM_REF`, `NODE_REF`, etc. mean an actual opaque `ref` returned by the matching query. Replace them before execution.
- `OBS` means the integer `observation` from the latest screenshot-bearing observation, not a frame number or filename.
- Stable `control` identifiers (such as `service_barter`, `trade_offer`, `rest_confirm`) are language independent. Names and captions must match the game's language exactly. English documentation does **not** make a Russian UI accept English labels.
- JSON arguments use JSON booleans (`true`/`false`) and double-quoted keys. Shell examples wrap the whole JSON in single quotes.
- Examples are individual decisions, not scripts to execute blindly. Inspect each result before its dependent step.

The CLI returns `{ "ok": true, "result": ... }` or `{ "ok": false, "error": "..." }`. A rejected request exits with a nonzero status. An `ok:true` action may still be blocked, interrupted, partial, or unsuccessful in the game.

## Read responses correctly

**Read/query:** `observe` returns the observation directly inside `result`. `status --player` returns character data there. `inspect inventory` returns a searchable page in `result.items`, plus weight/capacity; `ui` returns a searchable page in `result.elements`. Both report total/has_more. Use `--full` when every row is needed.

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
| `scene.objects` | Visible actors, doors, items, containers and activators; refs, categories, relative geometry and reach. `name` is optional: current close inspection or previously recognized instance. `description` requires current close inspection. |
| `details_visible`, `name_source` | Current tooltip-range inspection versus a remembered name. `name_source` is `observed` or `remembered` when `name` exists. |
| `actor_kind` | `npc` or `creature`; both keep `kind: "actor"`. |
| `memory_ref` | Persistent `object_…` handle for notes about this instance. Game actions still use the current `ref`. |
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
| `object_…` | `scene.objects[].memory_ref` or `knowledge objects` → `objects[].ref` | `knowledge add/list --object-ref`; never movement or interaction | Persistent within the atlas profile. A catalog entry is historical and does not prove that the object is currently visible. |
| `item_…` | `inspect inventory` → `items[].ref` | `use-item`, `select-enchanted` | Stable while that instance remains owned in the same game epoch. Refresh after load/restart, removal or a changed stack. |
| `spell_…` | `inspect spells` → `spells[].ref` | `select-spell` | Spell queries/actions can invalidate spell refs. Selection remains after its handle expires; refresh before a new selection. |
| `ui_…` | `ui` → `elements[].ref`, or observation's `ui.elements` | `choose`, `edit`, `adjust`, `hover` | Bound to the active menu and its meaning. Refresh after choosing/editing, changing selection, price, contents or modal. Fading notifications, tooltips and scrolling alone do not invalidate unchanged actions. |
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
| `ui [--control CONTROL]` | Current structured UI, including visible item tooltips; filter by stable control ID. |
| `target-info REF` | Read-only diagnostic for a currently visible object: aim correction, reach, readiness and current crosshair obstruction. Does not move or activate. |
| `read [--ref DOCUMENT_REF] [--offset N] [--limit N]` | Text of the currently open book/scroll. Default 4000 characters, maximum 8000 per chunk; no page turning or scrolling required. |
| `read --all` / `read --search "TEXT"` | Assemble the opened document internally, or return matching passages with Unicode offsets. |

Character summary includes identity, sign, level, health/magicka/fatigue, eight attributes, skills and progress, weight/capacity, gold, bounty, reputation, equipment/magic and active effects. Effects provide name/source, description, `harmful`, strength where applicable, affected attribute/skill, total/remaining duration or `permanent`. `from_equipment` marks an effect tied to equipped gear.

`body.levitation`, `water_walking`, `water_breathing`, and `slow_fall` mean the effect is active. They do not prove that the character is airborne, on the water surface, or safe from drowning. Check `on_ground`, `swimming`, `submerged` and observed movement.

Reading inventory does not open the inventory UI. `use-item` is for **owned** items; world pickups need `interact`. `inspect inventory` includes normal tooltip details, condition, charges/uses and known effects without opening the menu. Undiscovered ingredient/potion effects remain question marks.
