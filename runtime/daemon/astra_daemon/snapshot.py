"""Offline update snapshots; game assets and recordings are never rewritten."""
from pathlib import Path
import shutil
import sys
from .profile_data import copy_data, remove_data

NAMES=('profiles.json','profiles')


def snapshot(root: Path, operation: str, name: str):
    if not name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in name):
        raise ValueError('Invalid snapshot name')
    backup=root/'backups'/name
    if operation=='backup':
        backup.mkdir(parents=True,exist_ok=False)
        copy_data(root,backup)
        for item in NAMES:
            source=root/item
            if item=='profiles' and source.is_dir():
                for profile in source.iterdir():
                    if profile.is_dir():copy_data(profile,backup/item/profile.name)
            elif source.exists():shutil.copy2(source,backup/item)
        (backup/'complete').touch()
    elif operation=='prune':
        if not (backup/'complete').is_file():raise ValueError('Recovery snapshot must be complete before cleanup')
        for candidate in backup.parent.iterdir():
            if candidate.name.startswith('update-') and candidate!=backup and candidate.is_dir() and not candidate.is_symlink():
                shutil.rmtree(candidate)
    elif operation=='restore':
        if not (backup/'complete').is_file():raise ValueError('Incomplete snapshot')
        remove_data(root);copy_data(backup,root)
        for item in NAMES:
            source=backup/item;target=root/item
            if target.is_dir():shutil.rmtree(target)
            elif target.exists():target.unlink()
            if source.is_dir():shutil.copytree(source,target,symlinks=True)
            elif source.exists():shutil.copy2(source,target)
    else:raise ValueError('Unknown snapshot operation')


if __name__=='__main__':snapshot(Path('/data'),sys.argv[1],sys.argv[2])
