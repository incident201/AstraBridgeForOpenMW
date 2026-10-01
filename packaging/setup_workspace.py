#!/usr/bin/env python3
"""Create or remount a developer-selected file-backed build workspace as root."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner', required=True, help='Unprivileged build account')
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--mount', type=Path, required=True)
    parser.add_argument('--size-gib', type=int, default=128)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run this workspace setup as root; builds themselves run as --owner.')
    owner = pwd.getpwnam(args.owner)
    if owner.pw_uid == 0 or args.size_gib < 1:
        parser.error('Use a non-root owner and a positive workspace size.')
    for path in (args.image, args.mount):
        if path.is_symlink():
            parser.error('Image and mount must not be symbolic links.')
    image, mount = args.image.resolve(), args.mount.resolve()
    if image.is_relative_to(mount):
        parser.error('The backing image must be outside its mount directory.')
    if not image.exists():
        fd = os.open(image, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            os.ftruncate(fd, args.size_gib * 1024**3)
        finally:
            os.close(fd)
        subprocess.run(['mkfs.ext4', '-q', '-m', '0', '-i', '16384', '-L', 'AstraBuild', str(image)], check=True)
    elif not stat.S_ISREG(image.stat().st_mode):
        parser.error('The backing image must be a regular file.')
    if output('blkid', '-p', '-s', 'TYPE', '-o', 'value', str(image)) != 'ext4':
        parser.error('Existing image is not ext4; refusing to format it.')
    if output('blkid', '-p', '-s', 'LABEL', '-o', 'value', str(image)) != 'AstraBuild':
        parser.error('Existing image is not an AstraBuild workspace; refusing to reuse it.')
    mount.mkdir(mode=0o755, exist_ok=True)
    if os.path.ismount(mount):
        device = output('findmnt', '-n', '-o', 'SOURCE', '--mountpoint', str(mount))
        loops = json.loads(output('losetup', '--json', '--output', 'NAME,BACK-FILE'))['loopdevices']
        if not any(p['name'] == device and Path(p['back-file']).resolve() == image.resolve() for p in loops):
            parser.error('Mount belongs to another device; refusing to change it.')
    else:
        if any(mount.iterdir()):
            parser.error('Mount directory is not empty; refusing to cover existing files.')
        subprocess.run(['mount', '-o', 'loop,noatime', str(image), str(mount)], check=True)
    os.chown(image, owner.pw_uid, owner.pw_gid)
    os.chown(mount, owner.pw_uid, owner.pw_gid)
    for name in ('build', 'cache', 'containers', 'dist', 'downloads', 'run', 'tests', 'tmp'):
        path = mount / name
        path.mkdir(mode=0o700, exist_ok=True)
        os.chown(path, owner.pw_uid, owner.pw_gid)
    print(f'Workspace ready: {mount}\nOwner: {owner.pw_name}\nBacking image: {image}')


if __name__ == '__main__':
    main()
