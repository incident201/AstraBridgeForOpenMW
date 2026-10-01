# Project goals and information boundaries

## An interface designed for agents

AstraBridge's goal is to give an AI agent a practical way to play Morrowind. It
provides an abstraction layer over the game so the agent can concentrate on
understanding its surroundings, choosing goals, acting and checking outcomes.

This is deliberately **not a pure screenshots + mouse + keyboard benchmark**.
Screenshots remain part of observation, but the agent also receives structured
information and meaningful actions. The project does not aim to measure how
well a model can reproduce every mouse movement or keyboard event.

The analogy is a coding agent: we normally let it edit a file or write a whole
function. We do not require it to type the solution one simulated keypress at
a time. AstraBridge applies the same principle to game controls. An agent
should not have to recalculate a camera angle and assemble a sequence of raw
input events every time it wants to approach someone or select a dialogue topic.

The agent still decides what to do, interprets the result and handles failure.
AstraBridge supplies the control mechanisms; it does not supply a walkthrough,
choose quest solutions or decide the agent's goals.

## Assistance is an explicit part of the interface

### Movement, navigation and interaction

An agent can select an NPC it currently sees and request
`interact REF --approach`. AstraBridge can find a route, move the player, turn
toward the NPC and perform ordinary activation. It can update the approach as
the NPC moves. A blocked route, lost target, disabled player controls or a
popup can interrupt the action; reaching or activating the target is not
guaranteed merely because the request was accepted.

The navigation interface also provides bounded local movement candidates. An
agent facing a wall can learn that forward movement is obstructed while a
sideways or backward direction is available. These local probes can include
directions outside the current camera view. This is intentional navigation
assistance, not a complete map of unexplored areas.

Path-following commands use OpenMW's navigation facilities together with local
collision checks and, where appropriate, a route previously travelled by the
player. Ordinary movement and collision still determine where the character
actually gets to. Direct movement commands remain available, but do not
automatically plan a detour around an obstacle.

### Game UI

The agent can read structured controls from an open game interface and choose
a button, topic or item by a public handle. It can edit an input field or adjust
a slider without locating every control by mouse coordinates. The adapter uses
the existing game controls and their normal callbacks, including their
availability, prices and confirmation dialogs.

Accessibility includes populated rows of the current open list even when they
would require scrolling, and the formatted text of a book or scroll that has
already been opened. This removes presentation work; it does not reveal the
reply to an unselected dialogue topic or the contents of an unopened container.
Structured views of the player's own inventory, known spells and journal are
also available once the relevant game interface has been unlocked.

### Time and memory

The world pauses between completed or interrupted actions. Thinking time does
not advance NPC movement, consume an active effect's duration or run a quest
timer. Movement, turning, combat and waiting inside an action still consume
simulation time. This is a deliberate difference from a continuously running
human play session and should be stated when describing a benchmark.

This pause policy applies while an agent owns control. Desktop also supports
explicit manual control, with ordinary continuous play, when no agent is
connected. Watching through WebRTC does not advance the world or benchmark
recording clock. See [runtime architecture](architecture.md) for ownership and
the separate media timelines.

The agent can retain notes, learned names and travelled routes in persistent
memory. Loading an earlier save does not make it forget everything it learned
after that save. These records represent prior experience or agent-authored
notes, not a fresh reading of the current world.

## The information boundary

The intended rule is: **assist the agent with controls while grounding its
knowledge in what a player can observe, read or learn in the configured game**.
Convenient access to that information is allowed. An oracle for hidden world
or quest state is not.

| Subject | Available through the public interface | Boundary |
|---|---|---|
| Nearby world objects | Screenshot, broad kind, visible handle, relative distance/direction and interaction affordances. Actors can be distinguished as NPCs or creatures. | No enumeration of hidden NPCs or objects through walls. Object observations use the current view and visibility checks. |
| Unfamiliar names and descriptions | Names and available tooltip details after a permitted close inspection. | An unknown distant NPC, item, door or container does not acquire a name merely because the engine knows its record. |
| Door/container state | The available lock/trap description from a current close inspection. | Current lock/trap details are not restored from memory at a distance. |
| Container contents | Entries made available by the game's opened container/loot UI. | No raw inventory dump of an unopened container or another actor. |
| Player inventory and magic | Owned items, known spells, permitted effects and ordinary availability information. | Ownership and tutorial/interface restrictions apply. Unknown ingredient effects remain unknown. |
| Quests | Earned journal text, recorded conversations and what the current dialogue/UI actually presents. | No general query for quest-script variables, arbitrary journal indexes, hidden conditions or future dialogue responses. |
| Navigation | Local movement probes, selected visible destinations, progress/failure information and learned travel history. | No free overhead camera, complete unexplored map, raw navmesh export or public engine/world coordinates. |
| Memory | Previously observed names, places, routes, evidence and notes. | Historical or inferred information must not be presented as a new observation of current state. |

### Close inspection and recognition

The detail threshold follows the game's tooltip/activation distance, including
the implemented camera-distance and legal telekinesis adjustments. It is not
a fixed one-metre rule. A real activation target can also qualify. All visible
objects within the inspection range can reveal their permitted details; the
agent is not required to aim at each one individually.

Once a particular instance has been identified, its name can be recognized from
farther away on a later sighting. The response distinguishes
`name_source: "observed"` from `name_source: "remembered"`. It does not identify
every NPC or item sharing that instance's underlying game record. Current
descriptions and lock/trap state still require a fresh close inspection.

The agent acts on a current `ref`; its persistent `memory_ref` identifies a
memory entry. Notes may include an earlier lock observation or a hypothesis,
but do not bypass the live inspection rule or identify an unknown object.

### What the implementation may know internally

OpenMW necessarily holds the full game state. The controller and its Lua/native
adapters also use internal handles, geometry and game rules to execute actions.
For example, route following uses the engine's navigation mesh, and combat
assistance uses the player's equipment and reach calculations.

The boundary concerns the information and powers exposed to the gameplay
agent. Internal use of a quest condition by a declared gameplay addon is not
an API that lets the agent inspect that condition. Internal coordinates used
to follow a path are not a public global map. Conversely, adding a new output
field requires considering what it lets the agent infer, even if that field
was easy to obtain from an existing engine API.

## Enforcement and declared exceptions

The boundary is implemented across several layers:

- [Scene and visibility projection](../runtime/mod/scripts/astrabridge/scene.lua)
  selects observable objects and exposes public handles.
- [Recognition](../runtime/mod/scripts/astrabridge/recognition.lua) applies the
  inspection-distance rule; [knowledge memory](../runtime/daemon/astra_bridge/knowledge.py)
  removes private instance keys, validates the response and supplies learned names.
- The [native UI adapter](../runtime/native/astraui.hpp) reads active game UI,
  respects enabled/modal controls and excludes console/debug UI.
- The [protocol](../runtime/daemon/astra_bridge/protocol.py) limits accepted operations
  and result fields. The [skill](../skill/SKILL.md) forbids obtaining gameplay
  knowledge through game files, saves, private databases, developer logs or
  external walkthroughs.

**AstraBridge is not an operating-system sandbox.** An agent given unrestricted
shell and filesystem tools could bypass its public interface. Gameplay policy
and, where needed, a separately enforced tool/filesystem boundary remain part
of the evaluation setup. The project should not be described as making such
bypasses technically impossible.

The environment also has declared differences from an unmodified game:
the [bundled animation fix and Tribunal delay](mods-and-fixes.md), paused
reasoning time, persistent memory, and an explicit last-resort `resetNPC`
recovery operation. The latter uses the engine's ResetActors behavior and is
restricted by the skill to observed placement malfunctions, not ordinary
navigation or quest shortcuts. These choices should be disclosed when
comparing results with another environment or with human play.

## Guidance for contributors

When adding an observation or action, identify its player-facing source, the
conditions under which it becomes available, and the normal game mechanism
that performs the action. Keep historical knowledge distinguishable from live
state. Preserve visibility, ownership, modal and reach checks when adding a
new entry point, rather than relying on callers to use only the original one.

Use the [native inventory](openmw-modifications.md) to locate engine hooks and
the [mods inventory](mods-and-fixes.md) to understand environment changes. The
agent skill remains the operational command reference; these documents explain
the design and implementation behind it.
