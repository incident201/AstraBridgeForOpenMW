"""Keep local native/container builds on the explicitly selected filesystem."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


def check_workspace(work: Path, require_loop=False) -> Path:
    work = work.expanduser().resolve()
    if require_loop:
        info = json.loads(subprocess.check_output(
            ['findmnt', '-J', '-o', 'SOURCE,FSTYPE,TARGET', '-T', str(work)], text=True))['filesystems'][0]
        if not info['source'].startswith('/dev/loop'):
            raise ValueError('The selected workspace is not mounted from a loop device; prepare it with setup_workspace.py first.')
    work.mkdir(parents=True, exist_ok=True)
    for name in ('cache', 'containers', 'dist', 'downloads', 'run', 'tests', 'tmp', 'build'):
        (work/name).mkdir(exist_ok=True)
    return work


def environment(work: Path) -> dict[str, str]:
    return {**os.environ, 'TMPDIR':str(work/'tmp'), 'XDG_CACHE_HOME':str(work/'cache'),
            'PIP_CACHE_DIR':str(work/'cache/pip'), 'UV_CACHE_DIR':str(work/'cache/uv'),
            'npm_config_cache':str(work/'cache/npm'), 'ELECTRON_CACHE':str(work/'cache/electron'),
            'ELECTRON_BUILDER_CACHE':str(work/'cache/electron-builder'),
            'PLAYWRIGHT_BROWSERS_PATH':str(work/'cache/playwright'), 'PYTHONDONTWRITEBYTECODE':'1'}


def podman(work: Path) -> list[str]:
    return ['podman', '--root', str(work/'containers'), '--runroot', str(work/'run/podman')]
