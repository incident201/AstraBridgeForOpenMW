# Conditional waits and predictable sequences

Read this when the next few actions are already determined by observed information. All commands follow `astrabridge game`.

## Conditional waits and sequences

`wait-until fatigue --percent 100 --seconds 30` advances simulation until fatigue
reaches the requested percentage. Other waits include `wait-until landed`,
`wait-until animation`, `wait-until passage --bearing-deg B --meters M` (M≤6),
`wait-until ui --ui-mode MODE`, and `wait-until controls --control looking`.
The controls condition also accepts `controls` (default) or `jumping`.
Read `summary.reason`: `condition_met` confirms the condition;
`condition_timeout` means the budget expired. Death, unexpected UI/location or
`stop` can interrupt a wait. Resolve a modal through `ui` before waiting again.

`sequence` composes ordinary public actions, resolving owned item/spell names against fresh inventory/spell handles:

```sh
astrabridge game sequence '{"actions":[{"op":"use_item","name":"EXACT_OWNED_ITEM_NAME"},{"op":"wait_until","condition":"animation","seconds":5},{"op":"act","move":1,"seconds":3}],"max_seconds":15,"stop_on_damage":true,"stop_health_pct":35}'
```

Allowed `op` values are `"act"`, `"adjust"`, `"air_move"`, `"approach"`, `"buy"`,
`"cast"`, `"chain"`, `"choose"`, `"edit"`, `"fly"`, `"focus"`, `"go"`, `"interact"`,
`"jump"`, `"lock"`, `"look"`, `"move_local"`, `"rest"`, `"return_to"`, `"revisit"`,
`"select_enchanted"`, `"select_spell"`, `"strike"`, `"swim"`, `"target_info"`,
`"travel"`, `"trigger"`, `"unlock"`, `"use_item"`, `"wait_until"` and `"walk"`.
Use underscores in these operation names. Each step contains `op` plus that operation's normal fields. Item/spell selection also accepts an exact unique `name`. Every step is validated before execution. Do not preselect replies from dialogue that has not been opened/read.

A `select` object resolves a fresh handle immediately before its step. Filters: exact `name`, substring `contains`, `kind`, `panel`, `role`, `control`, `instance`, and scene-only `actor_kind` (`npc`/`creature`) and `nearest:true`. Source is inferred from the operation (`"scene"`, `"ui"`, `"inventory"`, `"spells"`). Scene name filters only match names currently exposed or previously recognized; they cannot discover an unknown distant name. Disabled, unavailable or ambiguous choices stop the sequence. `bind:"npc"` stores the selected handle; `ref:"$npc"` reuses it later, with normal visibility/freshness checks. For UI that changes, use a fresh selector at each step.

`expect` can check `ui_mode`, `location`, `location_changed`, action `outcome`, `gold_delta`, or `inventory_delta:{"name":"EXACT_NAME","delta":N}`. A failed check returns `expectation_failed` and skips all remaining actions. It cannot undo the completed step.

Example for an already opened dialogue offering barter:

```sh
astrabridge game sequence '{"actions":[{"op":"choose","select":{"control":"service_barter"},"expect":{"ui_mode":"Barter"}},{"op":"buy","name":"OBSERVED_ITEM_NAME","quantity":2,"max_total":50}],"max_seconds":30}'
```

Default total simulation budget is 60 seconds. `stop_on_damage` defaults to
true and `stop_health_pct` to 0 (disabled). Interruptions stop remaining steps;
already completed actions are not undone. Only the final observation captures a
screenshot. Individual steps can briefly pause between actions; use a combat
`chain` for continuous movement/casting, or `interact --approach` to approach and
activate together.

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

Read `action.steps` for individual results and `summary` for completion counts
and the stopping reason. Earlier steps may have changed the world even if a
later step failed.

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

Failure returns `expectation_failed`, includes the actual value in `action.steps[].checks`
and prevents subsequent steps. Basic horizontal-input failures are detected by
`summary` even without an explicit expectation. Thus jumping up and falling
back down against an obstacle cannot make a requested walk forward succeed.

Each `action.steps[]` entry retains its available `summary` and operation-specific details. The sequence's
summary preserves a failed/blocked/partial child result; it reports success only
when all steps and checks complete. `summary.stopped_step` locates the failed or
unstarted step. Read the summary status as well as its warnings.
An intentional out-and-back sequence may finish with zero endpoint displacement
and no warning if its individual movements succeeded.
