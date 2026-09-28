# Third-party notices

Original AstraBridge code, harness, Lua/native adapters, installer, build tools and
skill are licensed under GPL-3.0-only; see the root LICENSE. Copyright notices in
individual source files remain authoritative.

OpenMW 0.51.0 retains its upstream GPLv3 license and all notices in
`openmw-source/openmw-openmw-0.51.0/`, including separately licensed `extern/`
components. The project's version identifies the modified engine together with
the harness and skill; it does not change OpenMW's upstream version.

YAIAF 1.1 animation assets by Qlonever retain their original redistribution
permission in YAIAF.txt (also kept next to the mod). They are not relicensed.

Release libraries and Python wheels retain their own licenses. The packaging
script copies runtime library notices and wheel LICENSE/COPYING/METADATA files
into the release LICENSES directory and records their hashes in manifest.json.
Wheels include mss, Pillow and imageio-ffmpeg (including its FFmpeg executable).
They are downloaded only while building a release, never stored in Git.

Distributors must supply corresponding source for GPL/LGPL dependencies under
the applicable terms. Preserve package provenance and source/build information
with the release; notices alone do not replace corresponding source. OpenMW's
modified source is the release Git tag, with a source archive also emitted by
the release script.

The portable runtime also contains CPython from python-build-standalone. Its
pinned version, download URL and SHA256 are in `packaging/python-runtime.json`;
its license and bundled-library notices remain inside the release `python/` tree.
Ubuntu build-library copyright/source notices and exact installed package versions
are collected under release `LICENSES/debian/` and `debian-packages.txt`.
