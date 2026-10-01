# Documentation for people and developers

AstraBridge provides an agent-computer interface (ACI) for playing Morrowind
through OpenMW. These documents explain the project's purpose, implementation
and deliberate changes to the game environment.

| Document | What it covers |
|---|---|
| [System requirements](system-requirements.md) | Host dependencies, GPU access, storage and build tools. |
| [Project goals and information boundaries](project-goals.md) | Why the interface assists movement and UI interaction; what the agent may learn; limitations of the fairness claim. |
| [OpenMW modifications](openmw-modifications.md) | Inventory of the native changes, their purpose, affected source files and the division of work between C++, Lua and Python. |
| [Bundled mods and gameplay fixes](mods-and-fixes.md) | YAIAF, the generated Dark Brotherhood delay, profile settings and explicit recovery tools. |
| [Runtime and Desktop architecture](architecture.md) | Container lifecycle, managed data, host recordings, input ownership and platform boundaries. |
| [GPU selection](gpu-selection.md) | Independent rendering/encoding choices, probes and fallback behavior. |
| [Runtime API](runtime-api.md) | HTTP/WebSocket/WebRTC interfaces and the shared Desktop/CLI client. |
| [Recording and live media](recording.md) | Host recording files, encoder selection and independent recording/viewer timelines. |
| [Development and builds](development.md) | Local builds, tests, development mounts and release packaging. |

For installation, basic configuration and recording setup, use the
[main README](../README.md). For the public command reference and instructions
given to a gameplay agent, use the [agent skill](../skill/SKILL.md).

## Scope and source of truth

This inventory describes **AstraBridge 0.3.0 development**, using **OpenMW 0.51.0**
as the upstream baseline. The current project, upstream and protocol versions
are recorded in [VERSION.json](../VERSION.json). Source links point to the files
in this checkout; use a release tag when reviewing a frozen environment.

The inventory distinguishes four kinds of changes:

- Native engine adapters, compiled into OpenMW.
- Lua and Python code that implements the public ACI and its information rules.
- Animation assets and a locally generated gameplay addon.
- Profile settings and build/recording infrastructure.

This distinction matters when reproducing results or deciding whether a change
requires an engine rebuild. It also prevents a navigation helper or a gameplay
mod from being mistaken for an upstream OpenMW feature.

These are developer documents, not an additional source of game knowledge for
an agent during a playthrough. The skill defines that gameplay boundary. In
particular, the quest identifier documented for the Tribunal compatibility
addon is an implementation detail, not a public quest-state query.
