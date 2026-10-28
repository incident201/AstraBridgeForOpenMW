# Command conventions and responses

Use this reference for argument syntax, response fields and handle freshness. Read [UI](ui.md), [session/save/recovery](session.md), [sequences](sequences.md), [recording](recording.md), [information](information.md), [memory](memory.md), [navigation](navigation.md), or [combat](combat.md) only when relevant.

## Calling convention

Every gameplay command below follows `astrabridge game`. The permanent launcher
supplies the configuration recorded at CLI registration. For an export
without `command` in `installation.json`, use its executable and `--config` path.
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

**Most actions:** `result` contains `summary` (the effective outcome), `action` (movement and operation-specific details), and a new `observation` object. `feedback` is available in full responses. Some lifecycle/memory commands return other shapes. Do not assume every result has a nested observation.

Illustrative subset of a movement response:

```json
{
  "ok": true,
  "result": {
    "summary": {"status": "succeeded", "reason": "arrived", "destination_reached": true, "elapsed": 1.2},
    "action": {"motion": {"moved_m": 2.9}},
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
| `screenshot` | Current game-window image for visual inspection. |
| `observation` | Screenshot/observation number for coordinate-based UI operations. |
| `ui_mode`, `ui.modal`, `ui.elements` | Which menu is open, whether a modal blocks it, and actual controls. Tutorial popups can still report `Gameplay`. |
| `scene.objects` | Visible actors, doors, items, containers and activators; refs, categories, relative geometry and reach. `name` is optional: current close inspection or previously recognized instance. `description` requires current close inspection. |
| `details_visible`, `name_source` | Current tooltip-range inspection versus a remembered name. `name_source` is `observed` or `remembered` when `name` exists. |
| `actor_kind` | `npc` or `creature`; both keep `kind: "actor"`. |
| `memory_ref` | Persistent `object_…` handle for notes about this instance. Game actions still use the current `ref`. |
| `body` | Current support/swimming, animation, death, active mobility effects and control restrictions; changed gear/magic selection. |
| `stats`, `effects`, `combat` | Changed own resources, effect sources and attack/cast capabilities. Query `status --player` or `inspect` for complete current information. |
| `orientation` | Current heading/pitch; camera settings appear when first observed or changed. |
| `terrain`, `local_map`, `exploration` | Local navigation data and recorded travel memory; see navigation reference. |
| `messages`, `events`, `summary.events` | New observed messages, durable change events and confirmed action outcomes/interruptions. |

Responses focus on the requested operation:

| Operation | Context returned automatically |
| --- | --- |
| `observe`, `survey`, `scan` | Current surroundings, physical state and local passages. |
| Turning / `focus` | New orientation and visible targets; no automatic passage list. |
| Movement or a blocked movement attempt | Actual movement, obstacles, physical state, current targets and escape directions. |
| Menus, journal, dialogue and inventory UI | Outcome, current UI and meaningful changes; no automatic world or character dump. |
| Using an item, resting, selecting magic | Relevant resource/effect/selection changes; no automatic surroundings. |

World previews contain up to four objects (eight for explicit observations and
combat), with the selected target first. `has_more` means expand with `details scene`.
Background previews may omit `memory_ref`; get it with `details scene` for notes.
An omitted section was not reported by this command; it does not mean empty or
unchanged. Use `details SECTION`, `inspect VIEW`, `status --player` or `--full`
when needed. After UI-only commands, get current scene/passage refs with `details`
before using them. Unchanged Atlas identifiers and ordinary inactive flags are
omitted. Movement restrictions, dangerous state changes and required input remain
visible. `combat` and `effects` updates can contain changed fields only;
`effect_ended` reports removals. Inventory/spell rows omit `equipped:false` and
`selected:false`.

`action.motion` reports measured movement and turning. Zero components can be
omitted when `summary.horizontal_displacement_m` supplies the measured result;
`null` displacement remains unknown, not zero. `action.navigation` retains
remaining distance and obstruction/recovery diagnostics; use `--full` for details.

`submitted` means the request was sent, not that an item was equipped, purchased or a door opened. A spell attempt can have `action.reason=completed` (animation finished) but `summary.status=failed`, `summary.reason=spell_failed`, and `action.cast_outcome=failed`. Verify the relevant effect, inventory, menu, HUD, or message.

## Handles and freshness

| Value | Obtain from | Use with | Refresh rule |
|---|---|---|---|
| `visible_…` | `observe` / `details scene` → `scene.objects[].ref` | `focus`, `approach`, `interact`; actor refs also `lock`, `strike`, `cast`, `chain` | Use current scene refs; expand an omitted scene with `details scene`. Observe again if the target is lost. A remembered actor is not permission to track it through walls. |
| `object_…` | `scene.objects[].memory_ref` or `knowledge objects` → `objects[].ref` | `knowledge add --object-ref OBJECT_REF` / `knowledge list --object-ref OBJECT_REF`; never movement or interaction | Persistent within the atlas profile. A catalog entry is historical and does not prove that the object is currently visible. |
| `item_…` | `inspect inventory` → `items[].ref` | `use-item`, `select-enchanted` | Stable while that instance remains owned in the same game epoch. Refresh after load/restart, removal or a changed stack. |
| `spell_…` | `inspect spells` → `spells[].ref` | `select-spell` | Spell queries/actions can invalidate spell refs. Selection remains after its handle expires; refresh before a new selection. |
| `ui_…` | `ui` → `elements[].ref`, or observation's `ui.elements` | `choose`, `edit`, `adjust`, `hover` | Bound to the active menu and its meaning. Refresh after choosing/editing, changing selection, price, contents or modal. Fading notifications, tooltips and scrolling alone do not invalidate unchanged actions. |
| `document_…` | `ui.document.ref` or `read` | `read --ref` | Valid only for that opened book/scroll instance. Refresh after reopening or loading. |
| `passage_…` | `observe` → `terrain.passages[].ref` | `go` | Short-lived local sample; refresh after moving. |
| `ground_…` | `ground` → `ground_targets[].ref` | `go`, `walk --ref` | Short-lived visible-point sample; use promptly without moving first. |
| `node_…` | `atlas.nodes[].ref` or the observation's `exploration.current_node` | `revisit` | Persistent recorded node in this playthrough and space. Check `can_revisit` and `revisit_source`. |
| `place_…` | `remember`, `recall` | `return-to`, `connect` | A semantic note linked to its persistent atlas node; older notes without an Atlas link may no longer be usable for movement. |
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

Use `inspect stats` for skill progress, attribute damage and base/modifier details. Character summary includes identity, sign, level, health/magicka/fatigue, eight attributes and skill values, weight/capacity, gold, bounty, reputation, equipment/magic and active effects. `inspect effects` provides name/source, descriptions, `harmful`, strength where applicable, affected attribute/skill, total/remaining duration or `permanent`. `from_equipment` marks an effect tied to equipped gear.

`body.levitation`, `water_walking`, `water_breathing`, and `slow_fall` mean the effect is active. They do not prove that the character is airborne, on the water surface, or safe from drowning. Check `on_ground`, `swimming`, `submerged` and observed movement.

Reading inventory does not open the inventory UI. `use-item` is for **owned** items; world pickups need `interact`. `inspect inventory` includes normal tooltip details, condition, charges/uses and known effects without opening the menu. Undiscovered ingredient/potion effects remain question marks.

## Outcome summaries

Read `result.summary` first for ordinary actions, `revisit` and `sequence`:

| Field | Meaning |
|---|---|
| `summary.status`, `summary.reason` | Effective outcome and reason. Read these before deciding the next action. |
| `termination` | Present when different from `reason`, notably `time_limit` for a simulation/wall/turn/condition time limit. The specific reason remains alongside it. |
| `horizontal_displacement_m` | Measured horizontal distance between the action's start and finish. For a sequence/revisit, this is its overall endpoint displacement, not a sum of steps or travelled path length. `null` means a comparable measurement is unavailable, including a changed coordinate frame. |
| `destination_reached` | Present for navigation to a destination (`go`, `walk`, `move-local`, `fly`, `swim`, `revisit`, `return-to`). It reflects `arrived`; a general sequence has no inferred overall destination. |
| `encountered_blockers` | When present, distinct `blocked_by` values actually reported during the action, including earlier attempts. They describe history, not necessarily what is blocking the final position. No NPC or wall is inferred from a lack of progress alone. |
| `stalled_attempts` | When nonzero, reported no-progress/blocked attempts. This is separate from the reason the overall command ended. |
| `warnings` | When present, includes `no_horizontal_progress` when an explicit horizontal movement failed to advance; zero overall displacement by itself does not imply failure. |
| `completed_actions`, `total_actions`, `stopped_step` | When present, sequence counts and the one-based step that stopped or could not start. A completed input can still fail its expected result. |

For directed `act`, `jump` and `air-move`, `no_horizontal_progress` means the
requested horizontal movement made no meaningful advance. Rising or falling
alone is not horizontal progress. Very short inputs and stationary jumps are exempt. A confirmed activation combined
with unsuccessful movement is partial: its confirmed side effects remain in events.

## Keep outcome diagnostics in wrappers

AstraBridge already returns compact JSON. Forward that envelope as-is when
calling it from an agent tool. Keep the tool's output limit large enough for
complete JSON; use AstraBridge queries to request less data rather than cutting
the middle of a response. For example, with output strings in `stdout` and `stderr`:

```js
try {
  const response = JSON.parse(stdout);
  console.log(JSON.stringify(response));
  if (response.ok === false) process.exitCode = 1;
} catch {
  process.stdout.write(stdout); // Preserve a partial/non-JSON response.
  process.exitCode = 1;
}
if (stderr) process.stderr.write(stderr);
```

Do not reduce an action result to `result.action.reason`: `duration` can mean
input finished while `summary` reports failure. A sequence can also stop after
an earlier step already changed the world. If parsing/transport fails, preserve
the raw diagnostic and recover the receipt; do not assume the action did not run.

If a wrapper must filter output, retain `ok`, `error`, `message`, `request_id`,
`summary`, `action`, any extra `feedback`, and `observation` (including its
screenshot, messages and modal/body state). A screenshot path still needs to be
opened for visual inspection. Retrieve omitted steps using
`action-result REQUEST_ID --full`; a compact response keeps only the last eight
steps, while its summary was computed from the full result. Use
`action-result REQUEST_ID --section summary` to recover just that summary without
recapturing an image or advancing the game.
