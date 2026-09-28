# AstraBridge for OpenMW

Let an agent play Morrowind through the AstraBridge CLI and the `openmw-play`
skill. Originally developed for GPT-6 Astra; other models can use the same public
interface. Supply your own Morrowind installation; game files are never included.

## Install and play

```sh
git clone https://github.com/incident201/AstraBridgeForOpenMW.git
cd AstraBridgeForOpenMW
python3 install.py --game '/path/to/Morrowind'
```

Give your agent the **installed** `skill/openmw-play/SKILL.md` printed by the
installer, then play. The skill contains the installation's harness path.

The installer downloads a GitHub Release, verifies its SHA256 and file inventory,
creates a separate private runtime/config, configures Data Files, installs the
bundled Python wheels, installs the skill and runs doctor. It never builds OpenMW.
On a release-tag checkout it selects that tag; on main it selects latest stable.
The default destination is `~/AstraOpenMW/<tag>/`; existing installations and saves
are never overwritten. Use `--directory` for another new destination.

Requirements: Linux x86_64, Python 3.10+ to run the installer, an
X11/XWayland graphical session and working graphics drivers. The release manifest
states its minimum glibc and CPU ISA versions; the installer rejects incompatible
systems. Releases target ordinary **x86_64**, without an AVX2 requirement, and
**glibc 2.35 or newer** (Ubuntu 22.04/24.04 and compatible systems). No Arch
packages or package manager are needed. A pinned Python 3.12 interpreter and its
offline wheels are included, so the runtime does not use the system Python.
For English game data add `--encoding win1252` (default: `win1251`). Bootstrap is
offline, using wheels shipped in the release; downloading the release needs Internet.

```sh
python3 install.py --game '/path/to/Morrowind' --version latest
python3 install.py --game '/path/to/Morrowind' --version v0.1.0
# Optional agent discovery directory (must not already exist):
python3 install.py --game '/path/to/Morrowind' --skill-dir ~/.codex/skills/openmw-play
```

If doctor reports a missing display or host library, correct that prerequisite and
rerun `<installation>/AstraBridge/.venv/bin/python <installation>/AstraBridge/doctor.py`.
The installed runtime is retained for diagnostics. Start with
`<installation>/AstraBridge/astra start` from your graphical session.

## Frozen environments and benchmarks

`VERSION.json` defines one project version for harness, skill, modified OpenMW,
public protocol and binary bundle. OpenMW's upstream version remains 0.51.0.
The initial public protocol revision is **1**, matching the existing wire protocol;
project version and protocol revision need not increase together.

`main` is development. A `vX.Y.Z` tag plus its matching Release is the frozen
environment. Never move a published tag or replace its assets; corrections get a
new version. The release contains:

- `astrabridge-openmw-vX.Y.Z-linux-x86_64.tar.gz`
- `manifest.json` and `SHA256SUMS`
- `astrabridge-vX.Y.Z-source.tar.gz`

The archive contains `AstraOpenMW/engine/{openmw,lib,resources}`,
`AstraBridge/` (including offline wheels), `skill/openmw-play/`, `LICENSES/`, and
`manifest.json`, plus a private `python/` interpreter. No Morrowind files or user profiles are included.

The manifest records project/protocol/upstream versions, Git commit/tag, platform,
architecture, glibc/CPU ISA floors, engine hash, capabilities and hashes of every runtime
file. The external manifest also records the archive hash. The embedded manifest
has `asset_sha256: null` because an archive cannot contain its own hash; the
installer replaces it with the identical external manifest after verification.
`SHA256SUMS` covers the archive, external manifest and source archive.

Before every benchmark/playtest, save the public environment identity:

```sh
/path/to/AstraOpenMW/v0.1.0/AstraBridge/astra version > environment.json
```

It includes project version, protocol revision, environment commit, tag and actual
engine hash. Each session also writes an environment sidecar under its private
runtime, and each recording gets a `.environment.json` sidecar. Keep these with
benchmark results and record your game-data/mod configuration separately. Use the
same tag and verified release assets when comparing models.

## Development / build from source

Git contains source, skill, installer and build tools. Binaries, wheels, runtime
libraries, generated manifests and build outputs belong outside tracked files.

The release builder uses **Podman or Docker on the developer's machine** and an
Ubuntu 22.04 build container. GCC, headers and build packages stay in the container;
nothing is installed into the host system. End users need neither containers nor
a compiler, package manager, `zstd`, FUSE, or a separate Python runtime installation.

```sh
# First development build:
python3 packaging/build_release.py --development --work .release-work/dev --output dist/dev
python3 install.py --game '/path/to/Morrowind' --from-bundle dist/dev

# After editing sources: update the cached source tree and rebuild changed files
python3 packaging/build_release.py --development --resume --replace-output --work .release-work/dev --output dist/dev
```

Development builds may contain uncommitted edits and are marked as development
in the manifest. Add new source files with `git add` so they enter the source
snapshot; committing is only required for stable releases. `--jobs N` controls
parallelism. A changed container recipe/image requires a new work directory.

Work and output directories may be anywhere, including an external disk. With
Podman, `--container-storage /path/to/container-cache` also relocates the large
container images. No developer-specific paths are stored in the build recipe.

An engine-only native development build remains available with
`harness/native/build_engine.py`; its optional `--arch-deps` is an Arch-specific
**developer convenience**, not a release or installation requirement. Explicit
`--host-build --development` also permits native local bundle builds.

For a release, update `VERSION.json`, commit all changes, tag that clean commit,
and run the same packaging entry point. Use a fresh work/output directory:

```sh
git tag -a v0.1.1 -m 'AstraBridge 0.1.1'
python3 packaging/build_release.py --work .release-work/v0.1.1 --output dist/v0.1.1
(cd dist/v0.1.1 && sha256sum -c SHA256SUMS)
git push origin main v0.1.1
gh release create v0.1.1 dist/v0.1.1/* --verify-tag --title 'AstraBridge v0.1.1' --notes 'Frozen environment; see manifest.json.'
```

The packaging script builds modified OpenMW, copies resources and shared-library
closure/OSG plugins, includes xdotool, a pinned standalone Python and matching offline wheels,
gathers license notices and emits manifests/checksums. glibc and graphics
driver libraries remain host-provided. Build on the oldest supported target for a
lower glibc requirement; packaging computes the actual ELF symbol floor and
refuses stable releases that require newer than glibc 2.35. The archive uses gzip,
which the installer reads with the Python standard library.

To reuse a previously built engine, explicitly supply `--engine-prefix` and
`--engine-receipt`. The generated receipt records Git trees, actual source/native content digests
and `engine_sha256`; all must match this checkout and executable. This is a build-cache
path, never the ordinary install path. `--wheelhouse` and `--tools-prefix` accept
previously downloaded build inputs. Preserve dependency source/provenance and
notices when distributing third-party libraries; see `LICENSES/README.md`.

Run tests with `python3 harness/bootstrap.py --tests` then, from `harness/`,
`.venv/bin/python -m pytest -q tests ../packaging/tests`. Lua tests require `lua`;
window capture integration requires a configured test display. Packaging tests
exercise archive validation, hash mismatches and version selection without game data.

Manual fallback (installer internals): verify `SHA256SUMS`, safely unpack the
bundle into a new directory, then run `AstraBridge/configure.py`,
`AstraBridge/bootstrap.py --offline` and `.venv/bin/python doctor.py`. Prefer the
installer so that manifest validation and installed skill setup are also performed.

## License

Original AstraBridge, harness, skill, installer and build-tool code is distributed
under **GPL-3.0-only**, with the full GPLv3 text in [LICENSE](LICENSE). OpenMW keeps
its upstream GPLv3 license and copyright notices. Third-party components keep
their own terms; YAIAF's permission is in [LICENSES/YAIAF.txt](LICENSES/YAIAF.txt).
Release library and wheel notices are collected in `LICENSES/` in the bundle.
