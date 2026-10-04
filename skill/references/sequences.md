# Conditional waits and predictable sequences

Read this when the next few actions are already determined by observed information. All commands follow `astrabridge game`.

## Conditional waits and sequences

`wait-until fatigue --percent 100 --seconds 30` advances simulation until fatigue reaches the percentage. Other conditions are `landed` (ground support; see [jumping and falling](navigation.md#jumping-and-falling)), `animation` (idle/recovered), `passage --bearing-deg B --meters M` (locally clear, M≤6), `ui --ui-mode MODE`, and `controls` (player input enabled; optional `--control looking` or `jumping`). It returns `condition_met` or `condition_timeout`, with ordinary interruption on death, unexpected UI/location or `stop`. Waiting consumes game time. A modal can be open even in `Gameplay`; handle it through `ui` before waiting again.

`sequence` composes ordinary public actions, resolving owned item/spell names against fresh inventory/spell handles:

```sh
astrabridge game sequence '{"actions":[{"op":"use_item","name":"EXACT_OWNED_ITEM_NAME"},{"op":"wait_until","condition":"animation","seconds":5},{"op":"act","move":1,"seconds":3}],"max_seconds":15,"stop_on_damage":true,"stop_health_pct":35}'
```

Steps use API names with underscores: `act`, `jump`, `air_move`, `look`, `go`, `walk`, `revisit`, `return_to`, `approach`, `interact`, `move_local`, `use_item`, `select_spell`, `select_enchanted`, `cast`, `strike`, `chain`, `wait_until`, `trigger`, `choose`, `edit`, `adjust`, `focus`, `target_info`, `fly`, `swim`, `rest`, `buy`, `travel`, `lock`, `unlock`. Each step contains `op` plus that operation's normal fields. Item/spell selection also accepts an exact unique `name`. Every step is validated before execution. Do not preselect replies from dialogue that has not been opened/read.

A `select` object resolves a fresh handle immediately before its step. Filters: exact `name`, substring `contains`, `kind`, `panel`, `role`, `control`, `instance`, and scene-only `actor_kind` (`npc`/`creature`) and `nearest:true`. Source is inferred from the operation (`scene`, `ui`, `inventory`, `spells`). Scene name filters only match names currently exposed or previously recognized; they cannot discover an unknown distant name. Disabled, unavailable or ambiguous choices stop the sequence. `bind:"npc"` stores the selected handle; `ref:"$npc"` reuses it later, with normal visibility/freshness checks. For UI that changes, use a fresh selector at each step.

`expect` can check `ui_mode`, `location`, `location_changed`, action `outcome`, `gold_delta`, or `inventory_delta:{"name":"EXACT_NAME","delta":N}`. A failed check returns `expectation_failed` and skips all remaining actions. It cannot undo the completed step.

Example for an already opened dialogue offering barter:

```sh
astrabridge game sequence '{"actions":[{"op":"choose","select":{"control":"service_barter"},"expect":{"ui_mode":"Barter"}},{"op":"buy","name":"OBSERVED_ITEM_NAME","quantity":2,"max_total":50}],"max_seconds":30}'
```

Default total simulation budget is 60 seconds; it has no fixed upper cap. The total simulation deadline and health/damage guards are checked at dispatch and every motor frame, including long `act`, turns and individual casts/strikes. Frame timing and the final pause can add roughly a frame to the measured limit; submitted atomic UI operations cannot be undone. A combat `chain` uses its own continuous motor deadline. `stop_on_damage` defaults to true and `stop_health_pct` to 0 (disabled). Interruptions stop the remaining sequence; already consumed items are not replayed. Only the final observation captures a screenshot. Sequence boundaries retain ordinary brief command pauses; use a combat `chain` for continuous concurrent movement/casting, and `interact --approach` for uninterrupted approach/aim/activation.

## When to combine steps

Use `sequence` when each next step is already justified by the observed state.
Stop for a new agent decision at an unknown room, a new dialogue response, an
unclear obstacle or a route choice. The bridge does not decide those branches.

These are templates, not permission to spend gold, take items or enter unexplored
areas. Replace every placeholder with a currently observed value or a persistent
Atlas ref. Keep the default damage guard unless the situation warrants otherwise.

### Recover fatigue, then return to a known place

```sh
astrabridge game sequence '{"actions":[{"op":"wait_until","condition":"fatigue","percent":100,"seconds":30},{"op":"revisit","ref":"NODE_REF","seconds":30}],"max_seconds":60,"stop_on_damage":true}'
```

A wait timeout or popup prevents the navigation step. The destination must be a
place already known through the current profile's Atlas; this does not plan a
route to an undiscovered house.

### Use a familiar service menu

After reading the NPC's services and deciding to buy a specific item, the existing
barter example above combines the known service button with `buy`. The item name
and price limit are chosen by the agent from information already observed. Do not
preselect answers to unread dialogue or guess localized captions.

Steps such as `choose` and `interact` are allowed to open/change UI intentionally.
For those steps, use `expect` to check the intended UI or outcome before later
steps. An unexpected UI is not an unconditional stop for every operation.

### Pick up an observed item and verify ownership

```sh
astrabridge game sequence '{"actions":[{"op":"interact","ref":"VISIBLE_ITEM_REF","approach":true,"expect":{"inventory_delta":{"name":"OBSERVED_ITEM_NAME","delta":1}}}],"max_seconds":20,"stop_on_damage":true}'
```

Use an item whose identity/count have been observed and which you have decided
to take. A stack needs its observed count instead of an assumed one. A failed
check does not undo the interaction: inspect the returned result before retrying.

Only the final observation captures an image. Intermediate structured results,
`steps`, `completed_actions` and the stopping reason remain available. This saves
model round trips and screenshots without turning a sequence into an atomic
transaction. Individual steps can still have their ordinary brief pause boundary.

## Require a measurable horizontal displacement

Use `expect.min_horizontal_displacement_m` when a subsequent step should run only
after the current step has actually moved far enough in the horizontal plane:

```sh
astrabridge game sequence '{"actions":[{"op":"act","move":1,"seconds":3,"expect":{"min_horizontal_displacement_m":0.5}},{"op":"wait_until","condition":"fatigue","percent":100,"seconds":10}],"max_seconds":15}'
```

This checks the displacement of that step, in metres. The value must be finite
and nonnegative. It does not measure path length or prove progress toward a
particular destination. An unavailable/non-comparable measurement fails the
check, even for a zero threshold, with `actual:null` and
`reason: movement_not_comparable`.

Failure returns `expectation_failed`, includes the actual value in `steps[].checks`
and prevents subsequent steps. Basic horizontal-input failures are detected by
`feedback` even without an explicit expectation. Thus jumping up and falling
back down against an obstacle cannot make a requested walk forward succeed.

Each `steps[]` entry retains its `feedback` and available `summary`. The sequence's
feedback preserves a failed/blocked/partial child result; it reports success only
when all steps and checks complete. `summary.stopped_step` locates the failed or
unstarted step. Summary warnings do not replace a negative feedback status.
An intentional out-and-back sequence may finish with zero endpoint displacement
and no warning if its individual movements succeeded.
