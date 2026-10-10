# Information without repeated bulk output

## Choose the smallest useful response

- Ordinary action responses give a compact current observation, its screenshot, action outcome and important changes. Equipment condition, selected ammunition/charges and effect durations remain available in the summary. Repeated UI text is omitted when its revision is unchanged.
- `details SECTION` reads the latest observation without moving, querying a hidden source or creating a screenshot. Sections: `scene`, `ui`, `effects`, `combat`, `stats`, `body`, `terrain`, `exploration`, `messages`. Optional `--observation OBS` rejects an outdated snapshot. Lists accept `--query`, `--page`, `--limit`.
- `ui --query "TEXT" --panel repair` searches all rows of the currently opened menu, including rows outside the viewport. `--role`, `--page` and `--limit` narrow results. Opening a list does not reveal responses to topics that have not been selected or contents of closed containers.
- `inspect inventory --query "TEXT"` searches owned items. Entries include type, condition, charges/uses when applicable, normal tooltip information and opaque item/instance handles. `inspect spells --query "TEXT"`, `inspect journal --query "TEXT"` and `inspect conversations --query "TEXT"` work similarly.
- `read --search "TEXT"` searches the currently opened document. Use `read --offset N --limit L` for consecutive portions or `read --all` for a necessary full reading.
- `--full` requests the complete response. Prefer a section or search when a full response would repeat unrelated material.
- `scan` returns a short per-view list with heading, observation number, screenshot and landmarks, plus one final observation. `action-result REQUEST_ID --view N --section scene --query "TEXT"` retrieves a stored view; `--section ui` or `messages` retrieves its other public data. Views are zero-based. These are historical observations; their handles are not guaranteed usable in the current scene. Querying a receipt neither moves the camera nor advances the game.
- JSON uses compact formatting by default; `--pretty` adds indentation without changing content.

Pages are zero-based, normally 20 rows, with `total` and `has_more`; `--limit` supports 1–1000. Compact dialogue previews are at most 1600 characters and report `text_has_more`; `details ui` returns the complete current text. This response-size choice does not limit the underlying menu to its viewport. `ui --full` returns the whole current UI. A shortened action history reports `steps_total`; its receipt with `--full` retains every step.

Current object/UI refs are operational handles, not persistent identifiers for future sessions. Item refs survive ordinary actions and repeated inventory inspections while the same object remains owned; load/new-game/restart invalidate them. Separate `instance` handles match the same item between inventory and repair rows. Inventory stack splitting or merging may create a new instance: refresh and distinguish it by condition/equipment state instead of guessing.

## Object inspection and recognition

Scene objects have three forms (examples omit geometry):

```json
{"ref":"visible_session_1","memory_ref":"object_example","kind":"actor","actor_kind":"npc","details_visible":false}
{"ref":"visible_session_1","memory_ref":"object_example","kind":"actor","actor_kind":"npc","details_visible":true,"name":"Fargoth","name_source":"observed"}
{"ref":"visible_session_1","memory_ref":"object_example","kind":"actor","actor_kind":"npc","details_visible":false,"name":"Fargoth","name_source":"remembered"}
```

### First encounter

1. Run `astrabridge game observe` and view its screenshot. If a row says `kind: "actor"`,
   `actor_kind: "npc"`, `details_visible: false` and has no `name`, you see a person
   whose identity you have not yet learned. This is expected; nothing failed.
2. Choose the person using the screenshot, direction and distance. Copy that row's
   actual `ref` into `astrabridge game approach REF --reach activate`. Replace `REF` with
   the returned value; do not copy the illustrative `visible_session_1` above.
3. Read the action result and new observation. When close enough, the row has
   `details_visible: true`, its localized `name`, and `name_source: "observed"`.
   If the action was blocked or the target moved out of sight, reobserve and
   adjust your route. Use `interact REF` when you actually want to talk or activate.
4. After moving away, a visible recognized person can retain the name with
   `name_source: "remembered"` and `details_visible: false`. No further approach
   is needed just to recall the name. For a door/container, approach again before
   relying on its current lock/trap description.

The same process applies to creatures, items, doors, containers and activators.
The remembered name identifies an instance; it does not label every similar guard
or every item of the same type. Names can also coincide, so use current refs and
geometry to choose between two people with the same displayed name. A remembered
name survives a load, but its old action ref does not: obtain a fresh observation.

Approaching within the game's tooltip distance identifies all visible objects in
range, without individual aiming. Names come from the game's localized labels.
For unfamiliar distant objects, use refs, categories and visible geometry instead
of a name filter. Actors use `actor_kind: "npc"` or `"creature"`; selectors accept
this field for scene targets.

Recognized names are stored automatically in `runtime/agent-memory.sqlite3` using
the atlas's active profile. They survive controller restarts and loading earlier
saves, just like learned routes. Starting a new game selects another profile.
Only that particular instance is recognized; another guard or item with the same
record is still unfamiliar. When continuity cannot be verified, inspect it again.
The bridge does not add unseen objects or update their positions from memory.

Door/container `description`, including lock and trap information, is present only
while `details_visible` is true. A remembered name never implies that old details
are current. Historical observations can retain what was read at the time;
`details scene` describes its latest snapshot. `pick`, `target-info`, target locks,
`scan` and `--full` enforce the same inspection rule. Inventory and opened UI
continue to report the information available in those interfaces.

### Recover a command result

Choose an ID before submitting an important mutation:

```sh
astrabridge game use-item ITEM_REF --request-id heal-at-door-01
astrabridge game action-result heal-at-door-01
astrabridge game action-result heal-at-door-01 --full
```

Every ordinary command also returns an automatically generated `request_id`. `status.active_action` reports it while the command runs; `action-result` without a ref returns the most recent receipt. Result queries work while another action is active.

Use `action-result REQUEST_ID --section summary`, `--section action` or `--section feedback` to read only that part. Summary reads preserve the full-result diagnostics even when the original compact output omitted earlier steps. `--page` and `--limit` page action steps and observation lists; `--query` filters observation rows. The retained full receipt is available with `--full`.

Receipts live in `runtime/action-results.sqlite3`. Status is `submitted`, `completed`, `rejected`, or `unknown`. A controller restart converts unfinished receipts to `unknown`. Reusing the same ID and arguments returns the saved receipt under `response` and **never executes the action again**; using it with different arguments is rejected. `completed` means the command returned, not necessarily that the gameplay objective succeeded: check its action/feedback. `unknown` means the mutation might have happened. Observe/stop/recover before deciding on a fresh action; do not retry consumables on assumption.

Full responses are retained for the latest 1,000 finished requests, for up to
30 days; periodic cleanup removes older payloads. Pending requests are preserved.
After cleanup, `action-result` still returns the request's identity and original
status with `result_retained: false`, but no `response`. Section/view queries
then return `action_result_expired`. The same ID remains protected against
execution: missing old diagnostics do not authorize retrying a mutation.

## Choose text or an image

| Situation | Preferred information |
|---|---|
| New area, locating a passage, unclear obstruction or landing | Current screenshot plus structured observation |
| Reading dialogue, journal or an opened book | `ui`, `inspect journal`, `read`; view an image only if layout or ambiguity matters |
| Health, fatigue, stats, equipment or active effects | `status --player` / the relevant `inspect` view |
| Expanding the latest response | `details SECTION`, without taking another frame |
| Revisiting a `scan` angle | Its saved image and view index, without turning again |

Actions normally return a new observation already. Do not issue another `observe`
just to obtain the screenshot that is already present. For a successful `scan`,
`final.screenshot` is the same image as the last (fourth) returned view; there is
no need to open it twice. For an interrupted scan, `final` can be a new frame
showing a popup or other changed state: inspect the actual paths/result.

A stored image remains historical even if it looks unchanged. Only a current
observation supplies fresh handles and pixel coordinates. Runtime cache pruning
does not remove images an external model harness has already placed in its
conversation. Choosing not to open unnecessary images reduces repeated visual
input; this release does not deduplicate the model's history automatically.

For working-task recovery, durable notes and evidence, see [memory.md](memory.md).
