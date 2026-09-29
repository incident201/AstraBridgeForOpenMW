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

| Syntax, after `./astra` | Input / behavior |
|---|---|
| `look --heading H --pitch P` | Set either or both absolute angles. H=0…360, P=−80…80. Finite normal player turn; consumes time. |
| `act 'JSON'` | Direct movement/input for a caller-selected duration. Fields below. |
| `survey` | Refresh bounded local walking-surface samples; returns an action plus observation with `terrain`. |
| `ground` | Return `ground_targets`: visible walkable point candidates with refs, screen aim points, relative distances/heights and path status. |
| `go POINT_REF --seconds S --run --under-fire` | Follow a path toward a passage/ground/waypoint/walk ref. S≥0.5, default 12; no fixed upper cap. Flags are optional. **Not an actor or door ref.** |
| `pick X Y --observation OBS [--radius R]` | Ray-pick a visible object from the current image; radius 0 selects that pixel, R≤160 resamples a small screen region. Returns ordinary visible refs; geometry can occlude them. No movement. |
| `walk X Y --observation OBS --run` | Select a visible floor point from current screenshot pixels and walk toward it. The result can return a reusable `walk_…` ref. |
| `walk --ref POINT_REF --run` | Use a returned ground/walk reference. Do not combine `--ref` with X/Y/observation. Accepts `--seconds S` (default 8). |
| `move-local F --sideways-m R --seconds S --run --under-fire` | Direct movement to any finite relative horizontal offset; default time budget 30 s. Preserves its initial view direction, unlike path-following `go`. |
| `approach OBJECT_REF --reach activate --seconds S --run --under-fire` | Approach a visible object/NPC, including an unfamiliar target without a name. Its name/details become available within tooltip range. Reach can be `activate` (default), `melee` or `touch`; latter two are useful for actors. Does **not** activate it. |
| `focus OBJECT_REF --wait-ready` | Aim using an ordinary turn, without walking. `--wait-ready` can wait for a corpse to become lootable. Does **not** activate it. |
| `interact OBJECT_REF --approach --run --seconds S` | Approach, aim and activate in one continuous motor action (default 30 s); no intermediate thinking pauses. With interaction, up to two small physically checked viewpoint adjustments may be attempted; `--no-adjust-viewpoint` disables these. Without `--approach`, it does not perform a full approach. This is the normal talk/open/pickup command. |
| `fly --forward-m F --sideways-m R --vertical-m U --seconds S --under-fire` | Local flight, requiring active levitation. Defaults F/R/U=0, S=10; finite offsets with combined length >0.1 m; S≥0.2, no fixed upper cap. |
| `scan --pitch P` | Default pitch 0. Observe then turn through three 90° increments. Returns `views`, `final`, `completed`, `reason`, `elapsed`; does not restore the original heading. Requires no active live lock. |
| `fov DEGREES` | Set horizontal FOV within 70…115°. Default AstraBridge view is 100°. |

`walk` also accepts `--under-fire`. This flag disables the early damage stop for the movement commands that support it; it does not confer protection. Ordinary navigation can stop on damage, a changed location/UI, obstruction, lost target, time limit or partial path. Check the returned reason and actual distance, not just `ok:true`.

Path-following `go`/`walk` looks along its movement. A live combat lock controls the camera: `unlock` before independent turns/scans/path navigation. Combat pursuit/retreat intentionally keeps the actor in view; see [combat.md](combat.md).

An object may be above the standing surface, such as a hatch. Approach checks reach from the final eye position. Short missing navmesh connections may use `source: local_collision` after checking floor support and body clearance. A useful partial path can stop short and reports actual progress; it does not certify arrival. NPCs may move or disable player controls through a tutorial script. `player_controls_disabled` means wait or handle the current UI, rather than retrying movement against the restriction.

`scan` starts with a new observation. Each returned view includes its zero-based `view`, actual `heading_deg` and screenshot. Do not infer a view's angle from a previous observation or filename sequence. The final view is the current camera direction. Inspect omitted objects from one stored view with `action-result REQUEST_ID --view N --section scene`.

### Direct `act` fields

| JSON field | Range / default |
|---|---|
| `seconds` | Any finite number ≥0.02; default 0.25. No fixed upper limit. |
| `move` | −1…1; positive forward, negative backward; default 0. |
| `strafe` | −1…1; positive right, negative left; default 0. |
| `yaw` | Relative horizontal turn −180…180 degrees; positive right. |
| `pitch` | Relative vertical turn −90…90 degrees, clamped to the supported view range; positive down. |
| `run`, `sneak`, `attack` | Booleans, default false. `attack` holds ordinary Use during the step; prefer `strike`/`cast` for complete controlled uses. |
| `trigger` | One ordinary trigger such as `Jump` or `Activate`. Prefer `trigger Inventory/Journal/GameMenu/Rest` for menus. |
| `target` | Optional current visible-object handle for an already aimed, reachable activation. Prefer `interact` to manage aiming/reach. |

The action runs continuously for the requested duration, then releases controls and pauses the world. There is no periodic three-second pause; transport and engine watchdog timeouts scale with the requested duration. UI changes, cell changes, death or a lost combat target can still interrupt it. Choose the duration from the observed surroundings and how soon another observation is needed. An attack may still have an unfinished animation: read `body.animation_busy`. The next `act` defaults to not sneaking, so include `sneak:true` on each intended sneaking step; `look` preserves an existing crouch. `stop` clears it.

```sh
./astra act '{"move":1,"run":true,"seconds":10}'
./astra act '{"move":-1,"strafe":0.5,"seconds":0.5}'
./astra act '{"trigger":"Jump","move":1,"seconds":0.8}'
./astra act '{"sneak":true,"move":0.5,"seconds":1}'
./astra act '{"seconds":0.5}'
```

The final example waits without input. Finite turns/settling can make actual elapsed time differ from the requested movement duration; use the reported `elapsed` and `motion`.

## Local walking surface: JSON first, SVG optional

`observe` returns `terrain.passages` when available; `observe --full` also returns `terrain.rays`. Rays sample nearby directions; passages are candidate short moves with `ref`, `direction`, `bearing_deg`, `distance_m`, `height_change_m`, `slope` and `status`. The usual radius is 6 m. Gaps between samples are unknown.

`local_map` is an SVG of those same public data. Its top is **forward relative to the character**. Blue indicates rising terrain, orange descending, green approximately level. Request it with `observe --map`; ordinary observations generate no map files.

Use the numeric fields directly for simple decisions. For a confusing junction, view the rendered diagram alongside the actual game screenshot. Do not reconstruct world coordinates from diagram pixels or treat a ray as proof of a wide, unobstructed corridor.

Example decision sequence:

```sh
./astra observe
# Choose a current terrain.passages entry from its direction, clearance and height.
./astra go PASSAGE_REF --seconds 5
# Check action.reason, action.motion and the returned screenshot.
```

For a visibly reachable point not described well by a passage:

```sh
./astra ground
# Select a ground_targets entry after checking its screen location and navigation status.
./astra go GROUND_REF --seconds 8
```

`arrived` uses a tolerance reported by navigation. `partial`, `path_end_out_of_reach`, `blocked`, or `height_mismatch` do not mean the destination was reached. A bridge, stair or landing can be visible but not connected by the current navmesh. Choose another visible waypoint or a short direct action supported by the screenshot; do not force a hidden route.

`endpoint_mismatch` means the native path ended on a different height without a validated standing point or useful approach segment. An object approach may follow a useful native prefix, then replan; it reports partial progress if the destination remains unreachable. A short route may instead use physically sampled floor support (`navigation.source: local_collision`). Native navigation remains the default (`navmesh`). All movement uses normal collision and controls.

## Flight and water

Use `status --player` to confirm the active effect and its remaining duration before moving.

```sh
./astra fly --vertical-m 4 --seconds 8
./astra fly --forward-m 8 --sideways-m 2 --vertical-m -1 --seconds 10
```

`fly` uses normal movement and finite camera turns. It checks body clearance and can make short 3D detours around local obstacles. This is local assistance, not a global aerial map. Pure ascent/descent preserves horizontal heading. A visible object or ground handle can replace offsets: `fly --ref REF`. Release a live target lock first.

`go`, `walk`, `approach`, and `interact --approach` adapt to active levitation and movement-mode changes. `move-local` remains a horizontal ground operation and rejects active levitation. `fly` requires levitation; expiration while unsupported reports `levitation_ended` and pauses. Falling may resume when the next action advances time.

With water walking active, local paths and visible-point selection use the water surface, preserving bridges above it. `water_walking_ended` interrupts an affected route. An active effect does not by itself prove the feet are on the surface. Check `swimming`, `submerged`, `on_ground`, height changes and the image.

`swim --forward-m F --sideways-m R --vertical-m U --seconds S` requires the character to be swimming (default S=30). It also accepts `--ref REF`. Relative free-water movement uses local 3D collision checks; ordinary routes use native walking/swimming paths and replan at water/land transitions. Check breath, effect duration, observed movement and `navigation.movement_mode`. Ground combat maneuvers can still reject swimming.

## Travel memory: JSON nodes plus optional diagram

`atlas --radius-m R` returns recorded travel memory around the current pose. R≥0.1 m, default 35; no fixed upper cap. Normal `observe.exploration` is a summary with the current node and a loop hint. Use `atlas` for details.

Atlas is stored transactionally in `runtime/exploration-memory.sqlite3`; graphs, points and nodes have no retention-count limit. Private transforms align only the player's observed trajectory. The interface never exposes world coordinates or unseen geometry.

Access learned travel memory through `atlas`, `recall`, `revisit` and `return-to`. `runtime/userdata/navmesh.db` belongs to OpenMW's internal pathfinding cache. Direct agent access to that file or its copies/exports is forbidden during gameplay under the [mandatory gameplay boundaries](../SKILL.md#mandatory-gameplay-boundaries), including troubleshooting failed movement. Report a missing public capability instead of inspecting the cache. The engine's normal use of this cache through public navigation commands remains allowed.

```sh
./astra atlas --list
./astra atlas --space SPACE_REF --radius-m 80
./astra atlas --query "PLACE OR LANDMARK" --page 0 --limit 20
./astra atlas --level L2 --map
./astra atlas --route NODE_REF
./astra atlas --history --query "PLACE OR REASON"
```

`--list` lists stored spaces and observed directed door transitions. `--query` searches names, landmarks and location labels across this playthrough. `--page` is zero-based; `--limit` defaults to 20 (1…1000), with `total`/`has_more`. `--level` filters an observed height band, not an inferred architectural floor. `--route` previews known walking legs and door transitions without moving. A route may contain `native_path_required` legs between known points; these remain attempts until the engine confirms a path. Names attached by `remember` are accepted when unique. `--space` reads a graph from another location without moving; its view is centred on the last recorded pose, and `archived:true` marks that historical view. Use the node ref with `revisit` from the active location; reaching another space requires learned door transitions. Old JSON/checkpoint files are imported without deleting them. Old visits lacking a trustworthy coordinate transform remain readable archives; a matching checkpoint can align them when loaded.

Useful fields:

- `nodes[]`: `ref`, display `label` (A1, A2…), distance/bearing/height relative to the player, `visits`, `can_revisit`, `route_distance_m`, observed landmarks, screenshot references and `untraversed_directions`. `distance_m` is horizontal straight-line distance; `route_distance_m` follows recorded travel. `revisit_source: recorded_trail` means a connected recorded route exists. `native_path_required` means the point is known but the current position has no connected trail; the engine must find a valid path. `can_revisit` permits an attempt; doors or NPCs may still block it.
- `current_node`: the currently recognized recorded node, if any.
- `svg`, optional `png` (only with `--map`): visualizations of the travelled path and observed local probes. PNG is generated only when `rsvg-convert` is available. Open it explicitly; returning a filename does not show it to the model.
- `not_a_full_map`, `sampled_path`: reminders that the diagram is partial sampled memory.

Travel-memory diagrams use **north up**, unlike the local walking surface. Cyan is sampled travel, grey a different height, green observed probe rays, dashed lines directions not traversed. A dashed direction is not knowledge of what lies beyond it.

```sh
./astra atlas --radius-m 35
# Choose a nodes[].ref with can_revisit=true; A4 is a label, not the ref.
./astra revisit NODE_REF --seconds 10
```

`revisit NODE_REF [--run] [--seconds S] [--under-fire]` asks the motor to return to that recorded point. It is movement, not teleportation, and can fail or produce a partial path. Travel knowledge is persistent across cell visits, saves, loads and controller restarts. Loading an earlier save retains routes already learned in this playthrough; it does not imply that old doors, items or NPC states still apply. A new game uses a separate atlas profile.

Successful door links retain their approach and heading. Door links are learned only after actual crossings; the reverse direction is learned separately. `revisit` reacquires each door, turns to its observed heading and uses normal interaction, stopping on obstruction or an unexpected destination.

The motor first tries the engine's normal pathfinder. If that route is incomplete or crosses physical geometry, it can fall back to the recorded travelled path (`navigation.source: recorded_trail`). This includes the actual stairs and doorway turns. It never connects different floors just because their XY positions match, or draws routes over missing samples. Expired motor handles do not erase a recorded route.

At a learned door transition, the motor first matches fresh visible door geometry against its recorded center/floor. If needed it makes a bounded set of ordinary recorded camera turns. Old transitions without geometry require an unambiguous current label. Missing or ambiguous doors stop the route.

Collision is checked during movement. For a blocking NPC the motor briefly waits, then attempts a short local detour with floor support and both legs checked; otherwise it stops with an obstruction reason. Progress is measured along the route, with a short allowance for initial turning. Rotation or small oscillation does not reset the progress timer. `no_route_progress`/`repeated_positions` and the navigation reason identify stalled recovery. A closed door can block an older route. A time limit returns `step_limit`; continue from the current pose only if the result shows useful progress. Failed legs and successful traversals persist in the atlas. NPC blockages expire after eight simulation seconds, other route failures after 90; thinking on pause does not expire them. Loading/restarting revalidates old obstacles while preserving their history; `revisit` can try up to two alternative known legs within the original time budget. These cooldowns guide retries, not assertions that an obstacle still exists. `recorded_route_unavailable` means no route between known points/door links can be resolved. Long recorded paths are split internally into bounded motor legs and use the caller's total time budget; there is no 100 m limit on a connected recorded journey. A disconnected permanent point can use native navigation, without inventing a connecting trail.

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
| `return-to PLACE_REF --seconds S --run --under-fire` | Return to a note's persistent atlas node, including learned door transitions. Legacy notes without a verified atlas link still need a valid current-branch motor marker. |

For `return-to`/`revisit`, time defaults to 60 s and has no fixed upper cap. Always refresh `observe` before creating a note: `remember` uses the latest observation, not a fresh screenshot of its own.

Record visible landmarks, how you entered, and decisions at junctions. If a point has multiple visits and little new progress, inspect its past screenshots and choose a different observed route. Avoid repeatedly issuing the same blocked movement without new evidence.
