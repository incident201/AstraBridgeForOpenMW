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

1. Run `./astra observe` and view its screenshot. If a row says `kind: "actor"`,
   `actor_kind: "npc"`, `details_visible: false` and has no `name`, you see a person
   whose identity you have not yet learned. This is expected; nothing failed.
2. Choose the person using the screenshot, direction and distance. Copy that row's
   actual `ref` into `./astra approach REF --reach activate`. Replace `REF` with
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

### Notes about one object

Every safely matched visible instance has a `memory_ref`, even before you know its
name. Copy that value to attach notes, tasks or conversation reminders to that
particular NPC, creature, door or item. In these commands replace `OBJECT_REF` and
`NOTE_REF` with actual returned handles:

```sh
./astra knowledge add --kind note --object-ref OBJECT_REF --text "Door on the left of the stairs; inspect later"
./astra knowledge add --kind conversation --object-ref OBJECT_REF --text "Ask about the missing ring"
./astra knowledge list --object-ref OBJECT_REF
./astra knowledge update --ref NOTE_REF --status done
./astra knowledge objects --query "Fargoth"
./astra knowledge objects --object-ref OBJECT_REF
```

The catalog contains only previously encountered instances in the active atlas
profile. It reports remembered names/types and note counts; it supplies no current
position, visibility or lock state. The same note remains attached when a new
observation gives the object a different `visible_…` ref. Two similarly named
objects have separate memory refs and notes. When the object is visible again,
match its `memory_ref` in the new observation and use that row's `ref` for actions.

Notes are agent-written observations or hypotheses; adding a name in note text
does not teach the bridge that name. Use `--kind fact` only with the existing
observed-evidence/quote requirements below. Object notes follow the atlas profile
across older saves and restarts, and remain readable while the object is out of sight.

## Persistent tasks and evidence

Memory lives in `runtime/agent-memory.sqlite3`, separate from the spatial atlas. Use the public commands:

```sh
./astra knowledge add --kind task --text "Current objective and next step"
./astra knowledge add --kind conversation --text "Unfinished conversation and what to ask next"
./astra knowledge list --status open --query "TEXT"
./astra knowledge update --ref NOTE_REF --status done
./astra knowledge evidence --query "TEXT"
./astra knowledge evidence --ref EVIDENCE_REF --offset 0 --limit 4000
./astra knowledge add --kind fact --text "My summary" --evidence EVIDENCE_REF --quote "Exact supporting passage"
./astra knowledge events --page 0 --limit 20
```

`evidence_ref` identifies text already returned by dialogue, journal inspection or reading an opened document. It remains readable after the menu closes or the controller restarts. Fact summaries require a real evidence ref and an exact nonempty quote from it. They remain agent-written summaries; the quote supports review rather than certifying every inference. Tasks/conversation notes are explicitly agent notes. Status can be `open`, `done` or `abandoned`.

New inventory quantities, journal changes and effect start/end events are preserved separately from transient messages. An `event_id` can be found again through `knowledge events`. Repeated observations do not recreate the same change. Loading an earlier save resets change comparisons: old memory remains historical and is not proof of current ownership or quest state. Notes and evidence are not automatically injected into observations; query them on resume and when needed. Previously recognized instance names are supplied automatically as described above.

## Recover a command result

Choose an ID before submitting an important mutation:

```sh
./astra use-item ITEM_REF --request-id heal-at-door-01
./astra action-result heal-at-door-01
./astra action-result heal-at-door-01 --full
```

Every ordinary command also returns an automatically generated `request_id`. `status.active_action` reports it while the command runs; `action-result` without a ref returns the most recent receipt. Result queries work while another action is active.

Use `action-result REQUEST_ID --section action` or `--section feedback` to read only that part. `--page` and `--limit` page action steps and observation lists; `--query` filters observation rows. The full receipt remains available with `--full`.

Receipts live in `runtime/action-results.sqlite3`. Status is `submitted`, `completed`, `rejected`, or `unknown`. A controller restart converts unfinished receipts to `unknown`. Reusing the same ID and arguments returns the saved receipt under `response` and **never executes the action again**; using it with different arguments is rejected. `completed` means the command returned, not necessarily that the gameplay objective succeeded: check its action/feedback. `unknown` means the mutation might have happened. Observe/stop/recover before deciding on a fresh action; do not retry consumables on assumption.
