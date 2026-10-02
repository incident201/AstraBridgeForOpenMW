# Bundled mods and gameplay fixes

This inventory describes the environment prepared by AstraBridge 0.3.0 development. The
main content additions are an animation fix and a generated Tribunal delay.
Runtime settings and explicit recovery operations are listed separately because
they also affect how a playthrough behaves.

| Component | Origin | Default integration |
|---|---|---|
| Yet Another Idle Animation Fix (YAIAF) 1.1 | Third-party animation assets by Qlonever | Shipped in the Lua mod's data directory; additional animation sources enabled in the private profile. |
| Dark Brotherhood / Tribunal delay | AstraBridge-generated script override | Enabled when `Tribunal.esm` is active, unless `delay_tribunal` is explicitly disabled. |
| Testing defaults for combat | OpenMW settings chosen by AstraBridge | New profiles start with `difficulty = -100` and `best attack = true`; users may change both. |
| Synchronous physics at action boundaries | OpenMW setting applied by AstraBridge | `async num threads = 0` in the runtime profile. |
| Idle-camera stabilization | AstraBridge Lua policy using OpenMW camera interfaces | Disables automatic vanity/standing-preview behavior during controlled play. |
| Jump and fall controls | AstraBridge Lua adapter using normal actor controls | One jump impulse, directional air steering, observed flight state and stopping on landing; ordinary game physics and skill effects remain in force. |
| NPC placement recovery | Explicit public command using native ResetActors | Never an automatic part of navigation; the skill restricts its use to observed malfunctions. |

## Yet Another Idle Animation Fix

**Name:** Yet Another Idle Animation Fix (YAIAF), version 1.1.

**Author:** Qlonever.

### Problem and effect

Idle animation root motion can gradually displace an actor even though the
actor is meant to be standing still. A visible example is a transport NPC
drifting off a platform. This makes a persistent game environment unreliable:
an NPC's position can change because of animation drift rather than an AI
movement decision.

According to the bundled author documentation, YAIAF transfers that motion
from the root node to the pelvis bone. It preserves the visible animation
movement while preventing the idle animation from changing the actor's actual
coordinates. Its coverage includes ordinary standing and additional idle
states such as swimming, sneaking, casting, holding weapons and exhaustion.
This does not disable normal AI movement or solve every cause of a displaced NPC.

### Assets and activation

Three OpenMW animation files are shipped:

```text
runtime/mod/Animations/xbase_anim/_xYAIAF.kf
runtime/mod/Animations/xbase_anim_female/_xYAIAF.kf
runtime/mod/Animations/xbase_animkna/_xYAIAF.kf
```

[Session.prepare](../runtime/daemon/astra_bridge/session.py) adds the bundled mod data
directory to the private OpenMW configuration. When the bundled animation
asset is present, it enables:

```ini
[Game]
use additional anim sources = true
```

This uses OpenMW's additional-animation-source mechanism. It does not install
an ESP or replace the base skeleton NIFs in the user's game directory. Version
1.1's filenames are intended to load before other animations; another animation
mod can therefore affect the effective result. There is no separate YAIAF
toggle in the runtime configuration, and manually disabling the setting in the
generated profile is not persistent while `Session.prepare` enables it again.

The original [README](../runtime/mod/Docs/YAIAF%20README.txt),
[changelog](../runtime/mod/Docs/YAIAF%20CHANGELOG.txt) and
[redistribution permission](../LICENSES/YAIAF.txt) are retained. The assets keep
that permission; they are not relicensed under AstraBridge's GPL license.

## Dark Brotherhood / Tribunal delay

### Purpose and origin

AstraBridge defers the Tribunal assassination script until its main-quest
completion gate is reached. This avoids Dark Brotherhood attacks driving the
opening of an otherwise base-game playthrough.

This is **not a bundled copy of a third-party Dark Brotherhood delay mod**.
[tribunal.py](../runtime/daemon/astra_bridge/tribunal.py) generates a small OpenMW addon
from the effective `dbattackScript` in the user's own active content files.
The repository distributes the generator, not Bethesda's script text or a
prebuilt copy of the resulting game-content addon.

### Exact condition

The inserted guard returns from `dbattackScript` while:

```text
GetJournalIndex "C3_DestroyDagoth" < 50
```

At index 50 or above, the original script body is allowed to continue. It can
still apply its own timing and other conditions; reaching the threshold does
not itself spawn an assassin immediately.

This check is internal behavior of the configured addon. The numeric quest
index is not added to agent observations and does not provide a general
quest-state API. Gameplay knowledge continues to come from journal text,
conversations and the ordinary UI.

### Generation and load order

On `astrabridge start`, profile preparation:

1. Checks that `Tribunal.esm` is in the active content list and the feature is enabled.
2. Resolves content files using the configured data-directory order, including
   the `data-local` directory passed by the session.
3. Finds the last effective `dbattackScript` definition in the active load
   order, including an earlier mod's override.
4. Inserts the guard after local declarations and before executable statements,
   preserving the existing source bytes, localization and local-variable layout.
5. Writes `/data/runtime/data/AstraTribunalDelay.omwaddon` and appends it
   to the generated `/data/profile/openmw.cfg` content list inside the runtime.

The addon preserves the script header/local-variable information, replaces the
script source and clears the old compiled bytecode. OpenMW compiles that source;
the addon is specific to OpenMW and is not a ready-to-use plugin for the
original Morrowind executable.

The user's ESM/ESP files are read, not overwritten. Regeneration is deterministic
for the same inputs; an unchanged addon need not be rewritten. This does not
remove assassins already spawned, undo quest progress or rewrite a saved game.

### Configuration and compatibility

The feature defaults to enabled. To let another mod manage this behavior, set the following field in Desktop Settings or through
`astrabridge config set` while the game is stopped:

```json
{
  "delay_tribunal": false
}
```

The change takes effect on the next `astrabridge start`. Without active Tribunal
content, the generator is not applicable and no addon is enabled.

Using the last script definition preserves prior modifications to that script,
but is not a blanket compatibility guarantee. Generation rejects a missing,
deleted, truncated or source-less effective script, an already generated input
script, and unsupported nested `config=` arrangements. It is designed for the
flat private profile produced by the runtime storage service. A later plugin that replaces
`dbattackScript` can override the generated gate; do not assume the feature is
effective solely because an addon file exists.

Relevant checks: [generator/load-order tests](../runtime/tests/test_tribunal.py)
and [profile diagnostics tests](../runtime/tests/test_diagnostics.py).

## Runtime settings and control fixes

### Combat defaults chosen for testing

[Profile preparation](../runtime/daemon/astra_daemon/storage.py) seeds a new
managed runtime profile with the following settings:

```ini
[Game]
difficulty = -100
best attack = true
```

These are deliberate changes to the game's default settings, chosen for
convenience during testing. `difficulty = -100` lowers combat difficulty, and
`best attack = true` enables automatic selection of the weapon's best melee
attack type (chop, slash or thrust). The bundled OpenMW defaults are
`difficulty = 0` and `best attack = false`.

Neither setting is a fundamental limitation or requirement of AstraBridge.
Users may choose their preferred difficulty and attack behavior. These values
are initial defaults and are not forced back on each start.

Use Desktop Settings or, while the game is stopped, the application command:

```sh
astrabridge config set '{"difficulty":0,"best_attack":false}'
```

The settings take effect on the next game start. Changes made in the game's own
settings UI are retained by the runtime profile unless the user explicitly
applies replacement values through AstraBridge configuration. The profile lives
in managed storage at `/data/profile/settings.cfg` inside the runtime; normal
configuration does not require entering the container. Record the actual
settings when comparing playthroughs or benchmark results.

### Synchronous physics

Profile preparation enforces:

```ini
[Physics]
async num threads = 0
```

With asynchronous physics, a queued movement result can be committed when a
subsequent action starts. That can make an already reported paused position
drift. Synchronous physics keeps input, collision results and the action's pause
boundary in the same frame. This is a stability/performance tradeoff in the
private runtime profile, not a change to collision rules or player speed.

### Idle camera

[camera_policy.lua](../runtime/mod/scripts/astrabridge/camera_policy.lua) uses
the stock camera interfaces to disable automatic mode control and standing
preview. Scripted actions are not physical keyboard activity, so the ordinary
idle timer could otherwise begin a vanity orbit and separate the view direction
from the intended movement direction. If already in vanity/preview mode, the
policy returns to the primary camera mode. It does not introduce a free camera
for observing unexplored space.

### Explicit NPC placement recovery

`resetNPC --reason "..."` is a recovery operation, not a bundled mod. Its native
adapter invokes OpenMW's `resetActors()` for active cells; the Lua wrapper
invalidates affected scene/navigation handles and locks afterward.

The public command requires a reason. The skill additionally instructs the
agent to save first and use it only as a last resort for an observed placement
malfunction. The command does not enforce that save-first policy by inspecting
save history. It must not be used to solve ordinary pathfinding, combat or
quest problems. Record its use when reporting a playthrough or benchmark.

## Inspecting the configured environment

Desktop Settings exposes the configured gameplay/recording choices. Diagnostics
and the Runtime API report the engine, image, graphics and media environment.
The imported game directory remains unchanged: generated addons and prepared
settings live in the managed profile/runtime directories.

A configured addon or animation setting is evidence about prepared files, not
proof of universal compatibility with other mods. Retain the release identity
and actual game-data/mod configuration when comparing results. These choices
belong alongside the [project's information and control boundaries](project-goals.md).

## Jump and fall controls

The bundled Lua adapter provides `jump`, `air-move` and `wait-until landed`.
These compose normal player input: one jump impulse, optional Run and horizontal
steering during a jump or an ordinary fall. Landing ends the movement helper;
a short time budget can instead pause in midair for the next agent decision.
After contact, a brief update with movement input released lets normal landing
damage reach the result before pausing. The helpers preserve the current heading and require an active camera lock to
be released first.

`runtime/mod/scripts/astrabridge/airborne.lua` tracks the player's observed
height over simulation time, retains the last measured vertical speed across
pauses and resets on load or a position discontinuity. The player adapter
reports ground support, ascending/descending state, observed takeoff/landing,
relative peak height and health lost during an action. Compact observations
preserve explicit false ground/water flags. A Jump input without observed
takeoff is not reported as a successful jump.

This adds no jump power, air-control multiplier, double jump, teleport or
landing prediction. Existing OpenMW physics, collision, Acrobatics, fatigue,
launch momentum and fall damage determine the result. No additional native
engine patch or game-content plugin is required. Operational commands and
result interpretation are documented in the [gameplay skill](../skill/references/navigation.md#jumping-and-falling).
