#!/usr/bin/env python3
"""Reject generated executables, dependencies and build output in Git history."""
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
objects = subprocess.check_output(['git', '-C', str(root), 'rev-list', '--objects', '--all'], text=True)
forbidden = re.compile(r'(^build/|(^|/)wheelhouse/|\.(whl|so(\.[^/]*)?|dll|dylib|exe|tar\.(gz|xz|zst))$|(^|/)(ffmpeg|openmw\.x86_64)$|^runtime/(tools|runtime)/)')
paths = [line.split(' ', 1)[1] for line in objects.splitlines() if ' ' in line]
failures = sorted({path for path in paths if forbidden.search(path)})
tracked = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z']).decode().split('\0')
for name in filter(None, tracked):
    path = root / name
    if path.is_file():
        with path.open('rb') as stream:
            if stream.read(4) == b'\x7fELF': failures.append(name)
if failures:
    print('Generated binaries found:\n' + '\n'.join(failures), file=sys.stderr)
    sys.exit(1)
print('Source-only history verified.')
