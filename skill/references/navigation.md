# Navigation, maps and memory

Use current screenshots plus structured navigation data. The maps below are partial assistance, not a complete layout of the level. For handle types and result interpretation, see [commands.md](commands.md).

For places already visited, start with `atlas --query "NAME"` / `revisit`, or `recall` / `return-to`; see [travel memory](#travel-memory-json-nodes-plus-optional-diagram). A failed local route is not evidence that the remembered place was forgotten.

## Coordinate conventions

- Distances are metres; durations are simulation seconds.
- Absolute heading: 0° north, 90° east, 180° south, 270° west.
- Relative bearing: 0° ahead, positive to the right, negative to the left.
- Pitch: positive looks down, negative looks up.
- Forward/right distances are relative to the character's heading at the start of the command. Positive vertical distance means up.
- The agent receives relative geometry and public handles, not engine/world coordinates.

## Pick an operation

| Syntax, after `astrabridge game` | Input / behavior |
|---|---|
| `look --heading H --pitch P` | Set either or both absolute angles. H=0…360, P=−80…80. Finite normal player turn; consumes time. |
| `act 'JSON'` | Direct movement/input for a caller-selected duration. Fields below. |
| `jump [DIRECTION] [--run] [--seconds S]` | One normal jump; stops on landing or after S (default 8). Direction defaults to `none` for a vertical jump. |
| `air-move DIRECTION [--run] [--seconds S]` | Steer while jumping or falling; stops on landing or after S (default 0.5). No jump impulse. |
| `wait-until landed [--seconds S]` | Advance time without movement input until grounded (default budget 30 s). Preserves existing momentum. |
| `survey` | Refresh bounded local walking-surface samples; returns an action plus observation with `terrain`. |
| `ground` | Return `ground_targets`: visible walkable point candidates with refs, screen aim points, relative distances/heights and path status. |
| `go POINT_REF --seconds S --run --under-fire` | Follow a path toward a passage/ground/waypoint/walk ref. S≥0.5, default 12; no fixed upper cap. Flags are optional. **Not an actor or door ref.** |
| `pick X Y --observation OBS [--radius R]` | Ray-pick a visible object from the current image; radius 0 selects that pixel, R≤160 resamples a small screen region. Returns ordinary visible refs; geometry can occlude them. No movement. |
| `walk X Y --observation OBS --run` | Select a visible floor point from current screenshot pixels and walk toward it. The result can return a reusable `walk_…` ref. |
| `walk --ref POINT_REF --run` | Use a returned ground/walk reference. Do not combine `--ref` with X/Y/observation. Accepts `--seconds S` (default 8). |
| `move-local F --sideways-m R --seconds S --run --under-fire` | Direct movement to any finite relative horizontal offset; default time budget 30 s. Preserves its initial view direction, unlike path-following `go`. |
| `approach OBJECT_REF --reach activate --seconds S --run --under-fire` | Approach a visible object/NPC, including an unfamiliar target without a name. Its name/details become available within tooltip range. Reach can be `activate` (default), `melee` or `touch`; latter two are useful for actors. Does **not** activate it. |
| `focus OBJECT_REF --wait-ready` | Aim using an ordinary turn, without walking. `--wait-ready` can wait for a corpse to become lootable. Does **not** activate it. |
| `interact OBJECT_REF --approach --run --seconds S` | Approach, aim and activate in one continuous action (default 30 s); no intermediate thinking pauses. It may make small viewpoint adjustments to reach the target; `--no-adjust-viewpoint` disables these. Without `--approach`, it does not perform a full approach. This is the normal talk/open/pickup command. |
| `fly --forward-m F --sideways-m R --vertical-m U --seconds S --under-fire` | Local flight, requiring active levitation. Defaults F/R/U=0, S=10; finite offsets with combined length >0.1 m; S≥0.2, no fixed upper cap. |
| `scan --pitch P` | Default pitch 0. Observe then turn through three 90° increments. Returns `views`, `final`, `completed`, `reason`, `elapsed`; does not restore the original heading. Requires no active live lock. |
| `fov DEGREES` | Set horizontal FOV within 70…115°. Default AstraBridge view is 100°. |

`walk` also accepts `--under-fire`. This flag disables the early damage stop for the movement commands that support it; it does not confer protection. Ordinary navigation can stop on damage, a changed location/UI, obstruction, lost target, time limit or partial path. Check the returned reason and actual distance, not just `ok:true`.

`pick`, visible object refs and screenshot walking points use the current OpenMW
view distance. Read its current value with `details orientation`
(`view_distance_m`); observations report changed camera settings. The standard setting
is about 102.4 m; changing it changes selection range. This is the camera's
forward depth, so a visible point near a screen edge can be farther away in
straight-line distance. Occlusion and normal inspection/activation range still
apply. Selecting a distant target does not prove a complete route exists. A
returned walking goal can be continued with its ref after the camera turns;
fresh ground/passage selections still expire after moving 0.5 m or three
simulation seconds.

Path-following `go`/`walk` looks along its movement. A live combat lock controls the camera: `unlock` before independent turns/scans/path navigation. Combat pursuit/retreat intentionally keeps the actor in view; see [combat.md](combat.md).

Path-following commands can automatically take a short local detour around an
obstruction and rejoin their original route. This also applies to recorded
travel. You do not need to issue separate sidesteps for every rock: select the
observed destination, allow enough time for the route, then read the actual
result. Detours require floor support and body clearance and consume the same
action budget. They do not guarantee that every visible destination is
reachable. An obstruction, repeated positions or no route progress can still
stop the command; inspect its diagnostics and current screenshot before retrying.

On narrow stairs and bridges, choose a visible tread, landing or part of the deck with `ground` → `go`, or use `walk` on the screenshot. Check the point's height and navigation status. The route may first lead around a support post before climbing. `move-local` and `act` apply direct movement without planning that detour; after they stall, select a path-following command or a different visible intermediate point.

`move-local` checks progress toward its horizontal offset. The physical floor
can raise or lower the player along the way; this does not make the old starting
height a separate destination. Direct input still cannot plan around a wall.

`point_not_ground` means the selected pixel could not be resolved to a visible walking surface; no movement was started. It does not establish that the staircase or bridge is unreachable. Choose the centre of a visible tread/deck or a fresh `ground` ref. `ground` and `terrain.passages` are sparse samples: an omitted stairway may become selectable after turning, looking down or approaching its foot.

An object may be above the standing surface, such as a hatch. Approach checks reach from the final eye position. A useful partial path can stop short and reports actual progress; it does not certify arrival. NPCs may move or disable player controls through a tutorial script. `player_controls_disabled` means wait or handle the current UI, rather than retrying movement against the restriction.

`scan` starts with a new observation. Each returned view includes its zero-based `view`, actual `heading_deg` and screenshot. Do not infer a view's angle from a previous observation or filename sequence. On a completed scan, the last view is the current camera direction; after interruption, use `final`. Inspect omitted objects from one stored view with `action-result REQUEST_ID --view N --section scene`.

For a successful `scan`, the last view and `final` share one screenshot; an interrupted scan can have a different final frame. See [image selection](information.md#choose-text-or-an-image).

### Direct `act` fields

| JSON field | Range / default |
|---|---|
| `seconds` | Any finite number ≥0.02; default 0.25. No fixed upper limit. |
| `move` | −1…1; positive forward, negative backward; default 0. |
| `strafe` | −1…1; positive right, negative left; default 0. |
| `yaw` | Relative horizontal turn −180…180 degrees; positive right. |
| `pitch` | Relative vertical turn −90…90 degrees, clamped to the supported view range; positive down. |
| `run`, `sneak`, `attack` | Booleans, default false. `attack` holds ordinary Use during the step; prefer `strike`/`cast` for complete controlled uses. |
| `trigger` | One ordinary trigger such as `Jump` or `Activate`. Use `trigger Inventory`, `trigger Journal`, `trigger GameMenu` or `trigger Rest` for menus. |
| `target` | Optional current visible-object handle for an already aimed, reachable activation. Prefer `interact` to manage aiming/reach. |

The action runs continuously for the requested duration, then releases controls and pauses the world. UI changes, cell changes, death or a lost combat target can still interrupt it. Choose the duration from the observed surroundings and how soon another observation is needed. An attack may still have an unfinished animation: read `body.animation_busy`. The next `act` defaults to not sneaking, so include `sneak:true` on each intended sneaking step; `look` preserves an existing crouch. `stop` clears it.

```sh
astrabridge game act '{"move":1,"run":true,"seconds":10}'
astrabridge game act '{"move":-1,"strafe":0.5,"seconds":0.5}'
astrabridge game act '{"trigger":"Jump","move":1,"seconds":0.8}'
astrabridge game act '{"sneak":true,"move":0.5,"seconds":1}'
astrabridge game act '{"seconds":0.5}'
```

The final example waits without input. Finite turns/settling can make actual elapsed time differ from the requested movement duration; use `summary.elapsed` and `action.motion`.

## Jumping and falling

Read `body.on_ground`, `body.swimming` and `body.air_state` before choosing an
operation. These remain explicit in compact gameplay observations. `air_state` is
`grounded`, `ascending`, `descending`, `airborne` (near the apex or without a
reliable motion sample), `swimming`, or `levitating`. `vertical_speed_mps` is the
observed change in the player's height per simulation second: positive up,
negative down; ordinary grounded zero is omitted. It can also be absent just after loading or a
position discontinuity. The last measured speed is retained while paused; it
does not mean the player keeps moving between commands.

`jump` and `air-move` accept `none`, `forward`, `back`, `left`, `right`,
`forward-left`, `forward-right`, `back-left`, or `back-right`. Directions are
relative to the current heading, which these helpers preserve. `--run` holds
normal Run input. Release an active combat camera lock with `unlock` first.
The helpers use ordinary movement, collision, fatigue and Acrobatics; they do
not select a landing point or guarantee a distance. Inspect the screenshot to
choose a visible landing area.

```sh
# One directional jump, continuously controlled until landing (up to 8 seconds).
astrabridge game jump forward --run

# For a jump that needs correction, first take a short step into the air.
astrabridge game jump forward --run --seconds 0.3
# Read the returned screenshot and body state before deciding how to steer.
astrabridge game air-move right --run --seconds 0.3
# Once satisfied with the trajectory, let it finish without new movement input.
astrabridge game wait-until landed --seconds 8
```

`jump` requires ground support and enabled jumping. It releases crouch and
sends exactly one Jump impulse. `jump_requires_ground` means no new jump was
attempted; there is no double jump. `jump_not_started` means the impulse did
not produce an observed takeoff (for example, movement was obstructed).
`air-move` requires the player to be airborne; `airborne_required` means it
started on the ground. Levitation uses `fly`, and swimming uses `swim`.

A short `jump --seconds S` can return `reason: airborne`, `summary.status:
partial`: the jump started but has not finished. Read its state and continue
with `air-move` or `wait-until landed`, rather than retrying `jump`. The world
is paused at the end of each command even when the character is in midair.
A short `air-move` reports `duration` when its input budget finishes; that does
not imply landing. Both helpers stop movement on landing and report observed landing damage.
`landing_unstable` means support was lost again before the action finished;
inspect the current body state. Entering water reports
`entered_water`, with `landed:false`; switch to swimming controls if needed.
UI prompts, death, location changes and `stop` still interrupt the action.

The returned `action.aerial` contains `started_airborne`, `took_off`, `landed`,
`peak_rise_m` above the action's initial height, and `damage_taken` observed
during that action (including landing damage; it does not identify its cause).
`action.motion` reports actual forward/sideways/vertical displacement, including
the final pause. Check these and the final `body`; a completed input request
alone is not proof of a successful jump. `wait-until landed` can succeed
immediately if already grounded, in which case no new landing was observed.

Ordinary falls are steerable too: after walking off an edge, use `air-move`
without Jump. High Acrobatics improves air control. A moving jump carries its
launch momentum: releasing input does not brake it, and opposite input may
only reduce travel rather than reverse it. Turning the camera alone is not a
reliable way to redirect that momentum. Use directional steering and inspect
the observed result; no helper predicts unseen floor or guarantees a safe fall.

Low-level `act` with `trigger:"Jump"` remains available and reports the same
observed aerial evidence. `trigger Jump` is only a 0.1-second pulse wrapper;
it often leaves the character airborne. Low-level `act` runs for its requested
duration even after landing, and crouched jumping may produce no takeoff.
Prefer the helpers when landing is the intended stopping point.

## Local walking surface: JSON first, SVG optional

`observe` returns `terrain.passages` when available; `observe --full` also returns `terrain.rays`. Rays sample nearby directions; passages are candidate short moves with `ref`, `direction`, `bearing_deg`, `distance_m`, `height_change_m`, `slope` and `terrain.passages[].status`. The usual radius is 6 m. An omitted `clear_m` equals `distance_m`; omitted `height_change_m` is zero and omitted `slope` is level. Gaps between samples are unknown.

`local_map` is an SVG of those same public data. Its top is **forward relative to the character**. Blue indicates rising terrain, orange descending, green approximately level. Request it with `observe --map`; ordinary observations generate no map files.

Use the numeric fields directly for simple decisions. For a confusing junction, view the rendered diagram alongside the actual game screenshot. Do not reconstruct world coordinates from diagram pixels or treat a ray as proof of a wide, unobstructed corridor.

Example decision sequence:

```sh
astrabridge game observe
# Choose a current terrain.passages entry from its direction, clearance and height.
astrabridge game go PASSAGE_REF --seconds 5
# Check summary, action.motion and the returned screenshot.
```

For a visibly reachable point not described well by a passage:

```sh
astrabridge game ground
# Select a ground_targets entry after checking its screen location and navigation status.
astrabridge game go GROUND_REF --seconds 8
```

`summary.destination_reached:true` confirms arrival for point navigation.
`partial`, `path_end_out_of_reach`, `blocked`, `height_mismatch` and
`endpoint_mismatch` do not. Check actual movement and remaining distance; a
visible bridge, stair or landing may still lack a usable route. Choose another
visible waypoint or a short direct action supported by the screenshot.

## Flight and water

Use `status --player` to confirm the active effect and its remaining duration before moving.

```sh
astrabridge game fly --vertical-m 4 --seconds 8
astrabridge game fly --forward-m 8 --sideways-m 2 --vertical-m -1 --seconds 10
```

`fly` uses normal movement and finite camera turns. It checks body clearance and can make short 3D detours around local obstacles. This is local assistance, not a global aerial map. Pure ascent/descent preserves horizontal heading. A visible object or ground handle can replace offsets: `fly --ref REF`. Release a live target lock first.

`go`, `walk`, `approach`, and `interact --approach` adapt to active levitation and movement-mode changes. `move-local` remains a horizontal ground operation and rejects active levitation. `fly` requires levitation; expiration while unsupported reports `levitation_ended` and pauses. Falling may resume when the next action advances time.

With water walking active, local paths and visible-point selection use the water surface, preserving bridges above it. `water_walking_ended` interrupts an affected route. An active effect does not by itself prove the feet are on the surface. Check `swimming`, `submerged`, `on_ground`, height changes and the image.

`swim --forward-m F --sideways-m R --vertical-m U --seconds S` requires the character to be swimming (default S=30). It also accepts `--ref REF`. Relative free-water movement uses local 3D collision checks; ordinary routes use native walking/swimming paths and replan at water/land transitions. Check breath, effect duration, observed movement and `action.navigation.movement_mode`. Ground combat maneuvers can still reject swimming.

## Travel memory: JSON nodes plus optional diagram

`atlas --radius-m R` returns recorded travel memory around the current pose. R≥0.1 m, default 35; no fixed upper cap. Normal `observe.exploration` is a summary with the current node and a loop hint. Use `atlas` for details.

Use the public Atlas and note commands for travel memory. The
[gameplay boundaries](../SKILL.md#mandatory-gameplay-boundaries) also apply when
a remembered route fails.

```sh
astrabridge game atlas --list
astrabridge game atlas --space SPACE_REF --radius-m 80
astrabridge game atlas --query "PLACE OR LANDMARK" --page 0 --limit 20
astrabridge game atlas --level L2 --map
astrabridge game atlas --route NODE_REF
astrabridge game atlas --history --query "PLACE OR REASON"
```

Ordinary Atlas queries return nodes in the selected space; `--list` returns the global space catalog and observed directed door transitions. `--query` searches names, landmarks and location labels across this playthrough. `--page` is zero-based; `--limit` defaults to 20 (1…1000), with `total`/`has_more`. `--level` filters an observed height band, not an inferred architectural floor. `--route` previews known walking legs and door transitions without moving. A route may contain `native_path_required` legs between known points; these remain attempts until the engine confirms a path. Names attached by `remember` are accepted when unique. `--space` reads a graph from another location without moving; its view is centred on the last recorded pose, and `archived:true` marks that historical view. Use the node ref with `revisit` from the active location; reaching another space requires learned door transitions.

Useful fields:

- `nodes[]`: `ref`, display `label` (A1, A2…), distance/bearing/height relative to the player, `visits`, `can_revisit`, `route_distance_m`, observed landmarks, screenshot references and `untraversed_directions`. `distance_m` is horizontal straight-line distance; `route_distance_m` follows recorded travel. `revisit_source: recorded_trail` means a connected recorded route exists. `native_path_required` means the point is known but the current position has no connected trail; the engine must find a valid path. `can_revisit` permits an attempt; doors or NPCs may still block it.
- `current_node`: the currently recognized recorded node, if any.
- `svg`, optional `png` (only with `--map`): visualizations of the travelled path and observed local probes. Inspect the returned diagram alongside the game image.

Travel-memory diagrams use **north up**, unlike the local walking surface. Cyan is sampled travel, grey a different height, green observed probe rays, dashed lines directions not traversed. A dashed direction is not knowledge of what lies beyond it.

```sh
astrabridge game atlas --radius-m 35
# Choose a nodes[].ref with can_revisit=true; A4 is a label, not the ref.
astrabridge game revisit NODE_REF --seconds 10
```

`revisit NODE_REF [--run] [--seconds S] [--under-fire]` attempts to return to that recorded point. It is movement, not teleportation, and can fail or produce a partial path. Travel knowledge is persistent across cell visits, saves, loads and controller restarts. Loading an earlier save retains routes already learned in this playthrough; it does not imply that old doors, items or NPC states still apply. A new game uses a separate atlas profile.

Successful door links retain their approach and heading. Door links are learned only after actual crossings; the reverse direction is learned separately. `revisit` reacquires each door, turns to its observed heading and uses normal interaction, stopping on obstruction or an unexpected destination.

Recorded routes include stairs and changes of floor. A route can still be
blocked by a closed door, an NPC or changed geometry. Read `summary.reason`,
`summary.encountered_blockers` and any `action.navigation` diagnostics before
retrying. `no_route_progress` or `repeated_positions` means movement stalled;
a time limit alone does not establish why progress was poor.

`recorded_route_unavailable` means no usable connection through known routes and
door links could be resolved. There is no total-distance limit on a connected
recorded journey; allow enough time for its length. A known point without a
connected recorded trail may still be attempted when nearby, but this does not
prove that it is currently visible or reachable.

## Semantic notes and route history

These complement the automatically drawn travel path:

| Syntax | Purpose |
|---|---|
| `remember "LABEL" --note "TEXT" --confidence observed` | Attach a grounded note to the latest observation/current place. Use `inferred` for a hypothesis. Reusing a label updates that place in the current branch. |
| `remember "LABEL" --exits "DESCRIPTION" --exits "DESCRIPTION"` | Record observed exit descriptions; repeat `--exits` for each. |
| `recall "QUERY"` | Search notes by label/ref/text in the current branch; omit query to list recent notes. |
| `recall --archived` | Read notes from older branches too; treat them explicitly as historical, not current-state facts. |
| `connect PLACE_REF_FROM PLACE_REF_TO --via "OBSERVED_ROUTE"` | Record an agent-reported route between two known notes. Does not move or prove a path. |
| `route` | Recent actual movement steps and the status of the remembered anchor. Does not plan a route. |
| `return-to PLACE_REF --seconds S --run --under-fire` | Return to a note's persistent atlas node, including learned door transitions. Older notes without an Atlas link may no longer be usable for movement. |

For `return-to`/`revisit`, time defaults to 60 s and has no fixed upper cap. `remember` uses the latest observation; a current observation returned by an action is sufficient. Request `observe` if that snapshot is no longer current.

Record visible landmarks, how you entered, and decisions at junctions. If a point has multiple visits and little new progress, inspect its past screenshots and choose a different observed route. Avoid repeatedly issuing the same blocked movement without new evidence.

## Read a stopped revisit

`revisit`/`return-to` return a top-level `summary` separating the reason the command
ended from obstacles encountered earlier. For example, `termination: time_limit`
can coexist with `destination_reached:false`, `encountered_blockers:["actor"]`
and `stalled_attempts:2`. This does not establish that more seconds will solve the
route; inspect the current scene and navigation details before choosing a retry.
An `actor` blocker means an actor was actually detected; lack of progress alone does not identify one.

`action.attempts` retains each route attempt's reason and reported elapsed time. If a retry raises an error without returning
an action result, its entry has `result_available:false`; this is not proof
that no action was submitted. `action.steps`
retains compact movement/interaction results and their outcome summaries. Earlier blockers remain in the summary even when compact
output omits older steps; obtain the full receipt when investigating the path.
