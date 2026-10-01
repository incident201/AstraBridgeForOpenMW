# Development, builds and verification

## Source layout

- `runtime/daemon/astra_bridge`: existing gameplay, navigation, knowledge and
  recording implementation. Its command catalog is the CLI source of truth.
- `runtime/daemon/astra_daemon`: lifecycle, API, ownership, storage, manual input
  and live-media services.
- `runtime/native` and `openmw-source`: maintained native adapters, patch recipe
  and the patched OpenMW 0.51.0 source snapshot.
- `runtime/container` and `runtime/graphics`: image dependencies and private display.
- `desktop`: Application Core, Podman/WSL backends, Electron preload and Svelte UI.

The runtime API and Desktop are one application generation. There is no portable
Python installer or separate standalone gameplay CLI product. The internal
Python command module remains useful for schema generation and development tests.

## Workspace and native build

Use an explicit build workspace with adequate space and inodes. If the backing
filesystem has limited inodes, an optional file-backed ext4 workspace can be
prepared once with administrator privileges:

```sh
sudo python3 packaging/setup_workspace.py --owner YOUR_USER \
  --image /path/to/build-workspace.ext4 --mount /path/to/build-workspace
```

The image and mount paths are selected by the developer. Subsequent builds are
unprivileged. After a reboot, rerun the same setup command to remount the existing
image. The helper refuses to format an unrecognized existing file.

```sh
python3 packaging/build_runtime.py --work /path/to/build-workspace --jobs 3
```

Add `--require-loop` when a file-backed workspace is required by your environment.
It verifies that the selected workspace is mounted from a loop device. Ordinary
development filesystems and CI do not require this option. The builder stores its Podman
graph, downloads, compiler/FFmpeg build trees, Python cache and output in that
workspace. Native code is built in a builder container; the production image
does not include that toolchain or build tree.

Unchanged OpenMW inputs and builder identity reuse a verified engine receipt.
Changed native files retain Ninja/ccache state, including fetched dependency
sources. Python, Lua, Desktop and documentation changes do not require rebuilding
the engine. The FFmpeg prefix has its own pinned input receipt. `--cache-builder`
also exports/restores a builder image for CI caches.

The build creates a local OCI image and `WORK/dist/release.json`. It does not push
images, tags, commits or releases. Copy that release metadata to
`desktop/resources/release.json` before packaging the matching Desktop.

To transfer a local runtime to Windows without publishing it, export the image
with Podman's `save --format docker-archive` and load that archive using
`wslc image load --input <archive>`. Use the build workspace's Podman graph when
exporting. WSLC's archive loader requires Docker archive layout, even when the
original build produced an OCI image.

Loaded archives may have no registry digest. For a local `localhost/...` image,
set the development Desktop's `release.json` `digest` to the loaded image's
`Id` from `wslc image inspect`, preserving `development: true`. The Windows
backend uses that immutable config ID for creation, snapshots and rollback;
moving a local tag does not select different contents. Published releases still
require their registry manifest digest. Write edited JSON as UTF-8 without BOM.

## Desktop build

Use the pinned npm lockfile and Node 24 or newer. Keep caches and dependencies in
the selected workspace. If using a separate build filesystem, place the source
worktree there too so that `desktop/node_modules` uses the same filesystem.

```sh
cd desktop
npm ci
npm run build
npm run check
npm test
npm run package:linux
```

Set `npm_config_cache`, `ELECTRON_CACHE`, `ELECTRON_BUILDER_CACHE`,
`PLAYWRIGHT_BROWSERS_PATH` and `TMPDIR` to workspace directories. `ASTRA_BUILD_PYTHON`
selects Python for command-catalog generation. `ASTRA_RESOURCES`, `ASTRA_CONFIG`
and `ASTRA_DESKTOP_DATA` select development resources, a test installation and
isolated Electron user data. They do not expose private game files to the renderer.

The Linux launcher runs commands through Electron's bundled Node mode without
creating a GUI. Windows packages include the console launcher in
`desktop/packaging/launcher.cpp`; it uses the same compiled CLI/Application Core.

## Runtime development

Development enables the normal OpenMW console and explicit engine/FFmpeg
overrides. `astrabridge install --development --repository /path/to/repo` adds
writable repository/runtime mounts and a build-output mount for direct iteration.
Use the usual game/storage/encoding options too. Build native code with the
builder container, then select the resulting engine through the development
`engine_binary`/`engine_libraries` settings. Production uses its image's code and media
binary, a read-only game source and managed state. Host game-folder mounting is
also the normal production default; choosing `--game-mode copy` creates a managed
copy instead.

Use a separate installation/configuration for development tests. Loading a
developer save is an explicit test action, not automatic gameplay onboarding.
Preserve the [information boundary](project-goals.md) in the public Game API even
when the developer has direct access to the runtime.

## Tests

```sh
python3 -m pip install -r runtime/requirements-dev.txt
PYTHONPATH=runtime/daemon python3 -m pytest runtime/tests packaging/tests
```

Lua fixtures and a small native media-clock test complement Python tests.
Desktop checks cover command parsing, backend contracts and renderer typing.
The CPU recording smoke test uses generated frame/audio transport data and does
not require copyrighted game content or hardware encoding.

For an explicitly prepared GPU test installation and save:

```sh
python3 packaging/live_smoke.py --config /path/to/test-installation.json \
  --save-description "Test save" --output /path/to/check-results.json
```

This exercises both viewer qualities, concurrent recording, disconnect/reconnect
and a thinking pause. GL acceleration is established by an actual renderer probe;
encoder acceleration requires successful real-frame encoding.

## Release workflow

Releases are started manually with a version. CI checks source/CLI/runtime tests,
builds the cached native engine and pinned FFmpeg, builds/tests the OCI runtime,
packages Linux AppImage and Windows EXE, and creates a draft release. Desktop
metadata records the pushed OCI digest. Hardware-specific tests run separately;
they are not prerequisites for CPU-only CI builds.

Keep implementation details in `docs/` and public gameplay usage in the skill.
Update the engine/mod inventories with the corresponding changes. Preserve the
skill's general description and UI metadata unless explicitly requested otherwise.
