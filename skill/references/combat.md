# Combat, magic, combined actions and tools

All commands below are prefixed with `./astra`. References come from actual observations; see [commands.md](commands.md). This interface performs ordinary game actions: skill checks, animation time, resource costs and physics remain in effect.

## Select equipment and magic

| Syntax | Prerequisite / effect |
|---|---|
| `use-item ITEM_REF` | Ref from a fresh `inspect inventory`. Normal use/equip: weapon, armor, potion, etc.; verify the resulting state. Not a world pickup. |
| `select-spell SPELL_REF` | Ref from a fresh `inspect spells`. Select a known spell/power; does not cast it. |
| `select-enchanted ITEM_REF` | Select an owned cast-on-use/cast-once enchanted item. Does not use its charge yet. |
| `trigger ToggleWeapon` | Draw/holster the selected weapon or tool. Check `body.stance` before toggling. |
| `trigger ToggleSpell` | Enter/leave spell stance. Controlled `cast` normally handles preparation itself. |
| `inspect combat` | Read selected attack/cast details: reach, condition, ammunition, cost, availability, charge and effects. |

Item refs remain valid across ordinary actions while the same instance stays owned. Spell refs can expire after queries/actions; the selection itself persists, so `select-spell SPELL_REF` followed by `cast` is valid. Refresh an item after removal/merging or load/restart. `status --player` is safe for a quick read without invalidating handles.

## Target lock and one use

| Syntax | Arguments / behavior |
|---|---|
| `lock ACTOR_REF` | Aim at and lock a currently visible live actor. Also explicitly switches from another target. |
| `unlock` | Release the lock so independent looking/navigation can resume. |
| `strike [ACTOR_REF] --charge C` | One controlled attack, charge 0.1…1.5 s, default 0.8. Uses the supplied actor or current live lock. |
| `strike --air --charge C` | Intentional untargeted attack. Use `unlock` first, including after a down target; do not use it to bypass visibility/reach checks for a specific enemy. |
| `cast [ACTOR_REF]` | Cast the selected spell/enchantment. Self-only effects need no actor. Touch/target effects require a visible actor or suitable current lock. |
| `cast --air` | Intentional untargeted cast where appropriate; not compatible with a supplied ref or a retained lock; use `unlock` first. |
| `track ACTOR_REF --seconds S --attack` | Target tracking for any finite S≥0.1 (default 1), with no fixed upper limit; optional held attack. Prefer `strike`/`chain` when a complete attack cycle matters. |

A lock rotates the **character** with finite turn speed; it is not a detached camera. It cannot authorize following an actor through walls. Inspect `target_lock.status`. If an existing lock conflicts with a command, explicitly switch with `lock NEW_ACTOR_REF` or clear it with `unlock`.

`strike`/`cast` are bounded attempts, not guarantees of damage or success. Inspect messages, observed game HUD, `feedback`, resources and active effects. A visible corpse has `status:down`; `loot_ready` may remain false during its death animation.

For a target outside attack range, either `approach ACTOR_REF --reach melee` / `--reach touch`, or use `chain` with `pursue:true`. A standalone strike is not a promise to chase a distant actor.

## Action queues

Call `chain` with one JSON object:

```sh
./astra chain '{"ref":"ACTOR_REF","pursue":true,"actions":[{"op":"strike","charge":0.8},{"op":"strike","charge":0.8}],"max_seconds":12,"stop_health_pct":35}'
```

Replace `ACTOR_REF` inside the JSON with the actual opaque ref. The queue has **no pause between its steps**. Its final response has an observation and `action.steps`, `completed_actions`, `total_actions`, `elapsed`, resource changes and reason.

Top-level fields:

| Field | Allowed values / default |
|---|---|
| `actions` | Required nonempty array of steps (subject to the 32 KiB command transport limit), listed below. |
| `ref` | One actor target for target-dependent steps; omitted to use a live lock or for self-only actions. |
| `max_seconds` | Total finite simulation budget ≥0.5, default 12; includes approach/preparation. |
| `stop_health_pct` | Stop when own health reaches this percentage, 0…100; default 0 disables the condition. Not protection against a lethal hit. |
| `pursue` | Boolean, default false. Follow the selected visible actor and regain range as it moves. Incompatible with `movement` or `air`. |
| `movement` | Optional simultaneous directional maneuver, described below. |
| `air` | Explicit untargeted series; incompatible with `ref` and active lock. Not a hidden-target bypass. |

Step types are exactly:

```json
{"op":"strike","charge":0.8}
{"op":"cast"}
{"op":"cast","spell":"EXACT_KNOWN_SPELL_NAME"}
{"op":"cast","item":"EXACT_OWNED_ENCHANTED_ITEM_NAME"}
{"op":"wait","seconds":1}
```

- Strike charge: 0.1…1.5, default 0.8. Wait: any finite duration ≥0.02, default 0.5; the whole queue still stops at its `max_seconds` budget.
- A cast step can specify `spell` **or** `item`, never both. These are exact, unique display names from known spells/owned inventory, not engine IDs or refs. If ambiguous, select by a fresh ref first and use `{"op":"cast"}`.
- No UI click, inventory pickup, arbitrary key, movement command, or console command can be inserted as a step.
- Resource exhaustion, a changed UI/location, target loss/death, limits or health condition can stop a queue. Death of the target stops remaining target-dependent work; a different enemy is not selected automatically.
- An explicitly failed spell can finish its animation and the queue can continue to a retry. Its step carries `cast_outcome:failed`; a completed queue containing a known failed cast is reported as `partial` with `spell_failed`. Read the steps rather than counting every animation as successful magic.
- An intentional self-heal followed by a wait can allow a duration-based healing effect to take effect. Do not assume the full total healing happens immediately at cast completion.

## Move while attacking or casting

The `movement` object within a chain accepts:

```json
{"direction":"back","meters":2,"run":false,"face_target":true}
```

Directions: `forward`, `back`, `left`, `right`. Distance: ≥0.25 m, default 2. `run` and `face_target` are optional booleans. `face_target:true` requires a valid actor target/lock and keeps it in view. For deliberate movement without facing an actor, use `face_target:false` with **no** `ref` and no conflicting lock. A maneuver ends at its distance bound while the queue may still need to finish, or vice versa; inspect both action and movement reasons.

Examples:

```sh
# Approach a moving enemy and make several attempts without thinking pauses.
./astra chain '{"ref":"ACTOR_REF","pursue":true,"actions":[{"op":"strike"},{"op":"strike"},{"op":"strike"}],"max_seconds":15}'

# Keep facing the enemy while backing away and casting a known self-heal.
./astra chain '{"ref":"ACTOR_REF","movement":{"direction":"back","meters":2,"face_target":true},"actions":[{"op":"cast","spell":"EXACT_KNOWN_SELF_HEAL_NAME"},{"op":"wait","seconds":1}],"max_seconds":8}'

# Cast the currently selected self-only spell while moving forward independently.
# First clear a live actor lock if one exists.
./astra chain '{"movement":{"direction":"forward","meters":3,"face_target":false},"actions":[{"op":"cast"}],"max_seconds":8}'
```

These are ground maneuvers, not flight/swimming autopilots. They check local surface/obstacles, but do not automatically predict or dodge incoming arrows/spells. Choose the direction from visible evidence.

### Retreat and evade shortcuts

```sh
./astra retreat ACTOR_REF --meters 2 --seconds 4
./astra evade left ACTOR_REF --meters 2 --seconds 4
./astra evade right ACTOR_REF --meters 2 --seconds 4
./astra retreat ACTOR_REF --meters 2 --seconds 8 --actions '[{"op":"cast","spell":"EXACT_KNOWN_SELF_HEAL_NAME"}]'
```

`retreat` means `evade back`. The actor ref is optional only when a valid lock supplies it. `--run` is optional. Without `--actions`, seconds are ≥0.2 (default 4), distance ≥0.25 m (default 2). With `--actions`, the shortcut creates a face-target chain and uses `--seconds` as its total budget; use ≥0.5. No fixed upper cap is imposed. It does not mean "move, pause, then cast": movement and the queued uses run together.

## Ranged combat and multiple actors

Physical ranged weapons use aim assistance based on visible target motion and the selected weapon/ammunition. Read `aim_assistance`, trajectory/reach reasons and ammunition changes. A blocked trajectory, absent ammunition or submerged head can prevent firing. Magic projectiles do not have the same ballistic solver.

For multiple actors, choose the intended current visible ref, especially when names are identical. After `target_down`, inspect the scene and explicitly `lock` the next live actor before the next series. Do not keep attacking a corpse or infer all other nearby actors are enemies. The AstraBridge ACI does not provide an omniscient hostility list.

If a guard or other script opens a dialogue mid-fight, `ui_open` stops the queue. Handle the actual choices and close the dialogue before resuming. The reply itself may leave the dialogue open.

## Lockpicks and probes

There is no `pick-lock`/`disarm` high-level command. `strike` rejects tools as `not_a_weapon`. Use the ordinary tool input sequence, making decisions between steps:

1. Obtain the visible container/door ref. Approach it if necessary, then `focus` and read its normal lock/trap tooltip. Release any conflicting actor lock.
2. `inspect inventory` → choose the owned tool's current ref → `use-item ITEM_REF`.
3. Read `body.weapon` and `body.stance`. If not in weapon stance, `trigger ToggleWeapon`. Allow the draw animation to finish with a short `act` without attack; check `animation_busy`.
4. Refocus the intended container/door and confirm it is in reach. Send one short normal Use pulse:

```sh
./astra act '{"attack":true,"seconds":0.12}'
./astra act '{"seconds":0.8}'
```

5. Inspect the outcome before another attempt. The waits above are tested examples, not a guarantee every animation has finished on every configuration.

`combat.weapon_info` / `inspect combat` exposes own `tool_type`, `uses_remaining` and `quality`. Inventory UI item tooltips also show remaining uses. Observed notices include `lock_opened`, `lock_failed`, `lock_impossible`, `trap_disarmed`, `trap_failed`. An attempt can consume a use even when unsuccessful. After success, use ordinary `interact` to open the container and inspect its contents. Do not assume that unlocking also removes a trap.
