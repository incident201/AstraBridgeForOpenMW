# Bundled mods and gameplay fixes

This inventory describes the environment prepared by AstraBridge 0.2.2. The
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
harness/mod/Animations/xbase_anim/_xYAIAF.kf
harness/mod/Animations/xbase_anim_female/_xYAIAF.kf
harness/mod/Animations/xbase_animkna/_xYAIAF.kf
```

[Session.prepare](../harness/astra_bridge/session.py) adds the bundled mod data
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
toggle in `local-settings.json`, and manually disabling the setting in the
generated profile is not persistent while `Session.prepare` enables it again.

The original [README](../harness/mod/Docs/YAIAF%20README.txt),
[changelog](../harness/mod/Docs/YAIAF%20CHANGELOG.txt) and
[redistribution permission](../LICENSES/YAIAF.txt) are retained. The assets keep
that permission; they are not relicensed under AstraBridge's GPL license.

## Dark Brotherhood / Tribunal delay

### Purpose and origin

AstraBridge defers the Tribunal assassination script until its main-quest
completion gate is reached. This avoids Dark Brotherhood attacks driving the
opening of an otherwise base-game playthrough.

This is **not a bundled copy of a third-party Dark Brotherhood delay mod**.
[tribunal.py](../harness/astra_bridge/tribunal.py) generates a small OpenMW addon
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

On `astra start`, profile preparation:

1. Checks that `Tribunal.esm` is in the active content list and the feature is enabled.
2. Resolves content files using the configured data-directory order, including
   the `data-local` directory passed by the session.
3. Finds the last effective `dbattackScript` definition in the active load
   order, including an earlier mod's override.
4. Inserts the guard after local declarations and before executable statements,
   preserving the existing source bytes, localization and local-variable layout.
5. Writes `AstraBridge/runtime/data/AstraTribunalDelay.omwaddon` and appends it
   to the generated `AstraBridge/runtime/profile/openmw.cfg` content list.

The addon preserves the script header/local-variable information, replaces the
script source and clears the old compiled bytecode. OpenMW compiles that source;
the addon is specific to OpenMW and is not a ready-to-use plugin for the
original Morrowind executable.

The user's ESM/ESP files are read, not overwritten. Regeneration is deterministic
for the same inputs; an unchanged addon need not be rewritten. This does not
remove assassins already spawned, undo quest progress or rewrite a saved game.

### Configuration and compatibility

The feature defaults to enabled. To let another mod manage this behavior, merge
the following setting into `<installation>/AstraBridge/local-settings.json`:

```json
{
  "delay_tribunal": false
}
```

The change takes effect on the next `astra start`. Without active Tribunal
content, the generator is not applicable and no addon is enabled.

Using the last script definition preserves prior modifications to that script,
but is not a blanket compatibility guarantee. Generation rejects a missing,
deleted, truncated or source-less effective script, an already generated input
script, and unsupported nested `config=` arrangements. It is designed for the
flat private profile produced by `configure.py`. A later plugin that replaces
`dbattackScript` can override the generated gate; do not assume the feature is
effective solely because an addon file exists.

Relevant checks: [generator/load-order tests](../harness/tests/test_tribunal.py)
and [profile diagnostics tests](../harness/tests/test_diagnostics.py).

## Runtime settings and control fixes

### Combat defaults chosen for testing

[configure.py](../harness/configure.py) writes the following settings to
`<installation>/config/settings.cfg`, which seeds a new runtime profile:

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

Before the first start, edit `<installation>/config/settings.cfg` to change the
defaults used to create the profile. For an existing profile, use the game's
settings UI or, with AstraBridge stopped, edit the `[Game]` section in
`<installation>/AstraBridge/runtime/profile/settings.cfg`.
[Session.prepare](../harness/astra_bridge/session.py) preserves an existing
profile's difficulty and best-attack settings; changing only the seed file does
not update that profile. Record the actual settings when comparing playthroughs
or benchmark results.

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

[camera_policy.lua](../harness/mod/scripts/astrabridge/camera_policy.lua) uses
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

`AstraBridge/doctor.py` includes an `auto_fixes` report with
`scope: "profile_on_disk"`. The implementation is
[diagnostics.py](../harness/astra_bridge/diagnostics.py). It checks the prepared
profile and required assets without opening saves, the navigation cache or the
agent's spatial-memory database.

For example, a fresh installation may report `pending_start` until the profile
has been prepared. Tribunal delay can be `disabled`, `not_applicable`,
`needs_prepare`, `overridden` or `unverified`, depending on its configuration
and content. YAIAF checks cover the three animation files, the additional-source
setting and the bundled data path. Physics checks cover the profile setting.

`configured` is evidence about files on disk, not proof of the current state of
a running engine or of universal compatibility with other mods. Retain the
release identity and the actual game-data/mod configuration when comparing
results. These environment choices belong alongside the
[project's information and control boundaries](project-goals.md).
