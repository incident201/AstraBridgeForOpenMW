# AstraBridge for OpenMW

AstraBridge provides an agent-computer interface for playing Morrowind through
modified OpenMW. Desktop and its CLI manage one containerized runtime. Supply
your own Morrowind installation; game files are not included in the image.

## Requirements

- Linux x86_64: rootless Podman, a GPU driver and access to the GPU render device.
- Windows x86_64: WSL Containers (`wslc`), with GPU access.
- An existing Morrowind installation; extra disk space if choosing a managed copy.

Docker Desktop and a separate user-installed WSL distribution are not required.
See [system requirements](docs/system-requirements.md) for host dependencies and GPU setup.

## Install and play

Open the matching AstraBridge Linux AppImage or Windows installer/application.
In **Setup**, choose your game folder, managed storage, game encoding and an
optional recordings directory. By default AstraBridge mounts the game folder
read-only without copying. **Copy into managed storage** creates an independent
copy instead. Active content/archive order is imported from `Morrowind.ini`.
Review **Settings** before starting,
particularly for an installation without an INI file or with custom content.

The same application also provides CLI mode:

```sh
astrabridge install --game "/path/to/Morrowind" --storage "/path/to/AstraBridge" --encoding win1252
astrabridge start
astrabridge status
```

Use `win1251` for Cyrillic data, `win1252` for Western European data or `win1250`
for Central European data. Encoding is selected explicitly. On Linux the
AppImage itself accepts these commands; `astrabridge` above denotes that
executable. On Windows the installation includes an `astrabridge.exe` console
launcher. `--config FILE` selects a different application configuration.
Use `install --game-mode copy` for a managed copy; `mount` is the default.

The game appears in Desktop's **Play** viewer. When no agent is connected,
**Take manual control** enables mouse/keyboard input. Choose 720p30 or 1080p60
for the live view. Closing Desktop leaves the runtime and any agent/recording
running; use **Stop runtime** or `astrabridge stop` to stop them explicitly.

## Connect an agent

Use **Export gameplay skill** or:

```sh
astrabridge skill export "/path/to/openmw-play"
```

Give that exported folder to the agent. It contains the current gameplay
instructions and connection settings. Gameplay uses an explicit agent session:

```sh
astrabridge agent connect
astrabridge game observe
astrabridge agent disconnect
```

The viewer remains available while the agent controls the game; manual input is
disabled until the agent disconnects. The [skill](skill/SKILL.md) documents the
full gameplay interface.

## Recordings and updates

MP4 recordings and sidecars are written directly to a host folder, defaulting to
`<managed storage>/recordings`. Select another folder with `install --recordings
DIRECTORY`. Desktop can browse, play and open this folder; `astrabridge recordings`
reports it. Hardware encoding is probed automatically, with CPU fallback.

Install a newer Desktop package explicitly, then use **Update runtime** or
`astrabridge update` to install its matching image. Managed game/state data are
preserved. There are no automatic updates. Ordinary stop/restart does not remove
the persistent container or its data.

## Documentation

See [docs](docs/README.md) for project goals, OpenMW modifications, bundled fixes,
architecture, APIs, recording and development/build instructions.
