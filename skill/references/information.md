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

New inventory quantities, journal changes and effect start/end events are preserved separately from transient messages. An `event_id` can be found again through `knowledge events`. Repeated observations do not recreate the same change. Loading an earlier save resets change comparisons: old memory remains historical and is not proof of current ownership or quest state. Memory is not automatically injected into every observation; query it on resume and when needed.

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
