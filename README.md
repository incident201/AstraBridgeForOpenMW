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

## Source and licenses

OpenMW is an upstream GPLv3 project; its `LICENSE` and source copyright notices are retained under `openmw-source/`. License notices for libraries shipped with the Linux build are inside the archive. No separate license for the AstraBridge harness or skill was supplied with the source material; clarify their license before public release.

This repository intentionally excludes current-session data, Morrowind content, temporary build trees, virtual environments, generated logs, historical playtest reports, and Russian installation notes. This is the only README in the repository.
