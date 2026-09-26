# AstraBridge for OpenMW

This toolkit and gameplay skill let GPT-6 Astra play Morrowind through OpenMW. They were developed for Astra and will likely work with other models too.

The repository contains a modified OpenMW 0.51.0 engine, the AstraBridge Python/Lua controller, the skill, and a Linux x86_64 build. The bundled engine includes the **26 September 2026 persistent-atlas and completed-frame recording fixes**. Morrowind game files are not included; supply your own installation.

| Directory | Contents |
| --- | --- |
| `skill/` | The standalone `openmw-play` skill and its command references. |
| `harness/` | AstraBridge CLI, Python controller, Lua mod, tests, build helpers, and local runtime dependencies. |
| `openmw-source/openmw-openmw-0.51.0/` | Modified, buildable OpenMW source tree. |
| `build/` | Archive of the 26 September Linux build, build metadata, and SHA-256 checksums. |

The build archive was created from the installed engine that matches the local build output. It contains the engine executable, OpenMW resources, shared libraries, license notices, and a generic engine configuration. It does not contain a Morrowind installation, saves, recordings, screenshots, playthrough state, or a configured user profile. Historical export archives were not used.

## Install the Linux build

The binary targets a current CachyOS/Arch-like Linux x86_64 system with glibc 2.44 or newer, an X11/XWayland graphical session, and a working graphics driver. The runtime uses Python 3.11 or newer. The two Python wheels needed for offline bootstrap and a local `xdotool` are bundled in `harness/`.

From this repository, choose a separate installation directory:

```sh
cd build && sha256sum -c SHA256SUMS && cd ..
install_dir="$HOME/AstraOpenMW"
mkdir -p "$install_dir"
tar -xf build/openmw-astra-2026-09-26-linux-x86_64.tar.xz -C "$install_dir"
cp -a harness "$install_dir/AstraBridge"
cd "$install_dir/AstraBridge"
python3 configure.py --data '/path/to/Morrowind/Data Files' --recordings '/path/to/recordings'
python3 bootstrap.py --offline
.venv/bin/python doctor.py
./astra start
```

`configure.py` creates the private OpenMW configuration and runtime directories in the installation. It accepts a Morrowind root directory or its `Data Files` directory. The default text encoding is `win1251`; use `--encoding win1252` for English game data. Run `./astra observe` after startup to confirm that the game window is visible.

To install the skill for Codex, copy the entire `skill/` directory to `~/.codex/skills/openmw-play/`, then set `ASTRA_HOME` to the installed `AstraBridge` directory. The skill documents the public gameplay interface; it is not needed to build OpenMW.

## Build from source

`openmw-source/openmw-openmw-0.51.0/` includes the current engine changes corresponding to this bundle. The native UI adapter, completed-frame capture hook, and build helper are under `harness/native/`. On Arch-like systems with CMake, Ninja, a C++ toolchain, and OpenMW dependencies installed or available through `pacman`, run from the repository root:

```sh
python3 harness/native/build_engine.py --work "$PWD/openmw-source" --jobs 2
```

Add `--arch-deps` to download and unpack the required Arch packages into `openmw-source/deps/` without installing them system-wide. The helper builds the `openmw` target into `openmw-source/engine/`. The prebuilt archive includes additional runtime libraries and resources; rebuilding the executable alone does not recreate that archive.

Python/Lua tests are in `harness/tests/`. Run them from `harness/` with `python3 bootstrap.py --tests` followed by `.venv/bin/python -m pytest -q`. Lua tests also need a `lua` interpreter. The optional window-capture integration test requires its own configured X display.

## Persistent travel memory and recording

Atlas now stores each visited coordinate space in `runtime/exploration-memory.sqlite3` (SQLite WAL, full synchronous commits). Re-entering a cell, loading a save, or restarting the controller preserves its graph and stable node handles. There are no 12-visit, 5,000-point or 256-node eviction limits. `./astra atlas --list` lists stored spaces; `./astra atlas --space SPACE_REF` opens an archived view. Earlier saves retain learned travel knowledge; current movement still checks physical obstacles and NPCs. New games have separate profiles. Keep the entire private `runtime/` directory when migrating an installation; with the controller stopped, SQLite can be copied with its WAL/SHM files if present.

Existing exploration JSON and checkpoint files are imported without deletion. Legacy visits without a reliable origin stay archived until a matching checkpoint supplies the transform. The database records only travelled paths and observed local probes. Engine coordinates used to align the player's own trajectory remain private and are removed before public protocol validation.

Recording defaults to **60 fps, H.264 CRF 18**, without audio; thinking pauses are omitted. The engine copies the completed back buffer immediately before swap into a private shared-memory ring, avoiding compositor tearing and stale window captures. A separate encoder thread and timestamp resampler preserve frame pacing. Status/sidecar JSON reports actual rendered frames, repeated frames, ring overruns, queue depth and frame intervals. Loading or an overloaded renderer can still repeat frames; nominal 60 fps does not hide those counters. The current stream supports frames up to 1920×1080; the configured game window remains 1280×720. Resizing during a recording requires starting a new clip.

Use the updated harness **and** engine together. Recording with an older engine fails explicitly. This Linux x86_64 capture hook is opt-in through the controller's private `ASTRA_FRAME_STREAM` environment variable; ordinary OpenMW launches are unaffected. Completed frames also supply current screenshots. The stream file lives in private runtime storage and is removed on shutdown.

On an RTX 3060 Laptop GPU, a continuous 20-second navigation test produced 1,200 captured and encoded frames with zero repeats or ring drops. The full 51.067-second interior/exterior test produced 3,064 output frames, 12 repeats and zero ring drops; median frame interval was 16.660 ms, p95 17.655 ms. These are measurements from that scene, not a guarantee for every machine or loading screen.

## Source and licenses

OpenMW is an upstream GPLv3 project; its `LICENSE` and source copyright notices are retained under `openmw-source/`. License notices for libraries shipped with the Linux build are inside the archive. No separate license for the AstraBridge harness or skill was supplied with the source material; clarify their license before public release.

This repository intentionally excludes current-session data, Morrowind content, temporary build trees, virtual environments, generated logs, historical playtest reports, and Russian installation notes. This is the only README in the repository.
