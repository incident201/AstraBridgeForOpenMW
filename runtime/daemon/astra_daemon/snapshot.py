"""Offline update snapshots; game assets and recordings are never rewritten."""
from pathlib import Path
import shutil
import sys

NAMES=('profile','saves','sessions','atlas','configuration.json','storage.json')


def snapshot(root: Path, operation: str, name: str):
    if not name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in name):
        raise ValueError('Invalid snapshot name')
    backup=root/'backups'/name
    if operation=='backup':
        backup.mkdir(parents=True,exist_ok=False)
        for item in NAMES:
            source=root/item
            if source.is_dir():shutil.copytree(source,backup/item)
            elif source.exists():shutil.copy2(source,backup/item)
        (backup/'complete').touch()
    elif operation=='restore':
        if not (backup/'complete').is_file():raise ValueError('Incomplete snapshot')
        for item in NAMES:
            source=backup/item;target=root/item
            if target.is_dir():shutil.rmtree(target)
            elif target.exists():target.unlink()
            if source.is_dir():shutil.copytree(source,target)
            elif source.exists():shutil.copy2(source,target)
    else:raise ValueError('Unknown snapshot operation')


if __name__=='__main__':snapshot(Path('/data'),sys.argv[1],sys.argv[2])
