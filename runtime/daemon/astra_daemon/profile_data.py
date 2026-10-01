"""Persistent profile files; engine transports and caches are disposable."""
from pathlib import Path
from contextlib import closing
import shutil
import sqlite3

DATA = ('profile', 'saves', 'sessions', 'atlas', 'configuration.json', 'storage.json',
        'runtime/screenshots', 'runtime/action-results.sqlite3')


def copy_data(source: Path, destination: Path, *, rebase=False):
    replacements = [(str(source/name)+'/', str(destination/name)+'/')
                    for name in ('profile', 'saves', 'sessions', 'atlas', 'runtime/screenshots')]

    def text(value):
        if rebase and isinstance(value, str):
            for old, new in replacements:value = value.replace(old, new)
        return value

    def copy_file(src, dst):
        src, dst = Path(src), Path(dst)
        if src.is_symlink():raise ValueError('Profile data must not contain symbolic links')
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == '.sqlite3':
            # A completed backup includes committed WAL data without sharing a DB.
            with closing(sqlite3.connect(src.as_uri()+'?mode=ro', uri=True)) as original:
                clone = sqlite3.connect(dst)
                try:
                    original.backup(clone)
                    if rebase:
                        clone.create_function('astra_rebase',1,text)
                        for (table,) in clone.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
                            quoted = '"'+table.replace('"', '""')+'"'
                            columns = [row[1] for row in clone.execute('PRAGMA table_info('+quoted+')')]
                            setters=[]
                            for name in columns:
                                column='"'+name.replace('"','""')+'"'
                                setters.append(column+'=astra_rebase('+column+')')
                            clone.execute('UPDATE '+quoted+' SET '+','.join(setters))
                        clone.commit()
                finally:clone.close()
        elif rebase and src.suffix in ('.json', '.jsonl', '.cfg'):
            dst.write_text(text(src.read_text()))
        else:shutil.copy2(src,dst)

    def ignore(directory,names):
        for name in names:
            if (Path(directory)/name).is_symlink():raise ValueError('Profile data must not contain symbolic links')
        return [name for name in names if name.endswith(('-wal','-shm'))]

    for name in DATA:
        src, dst = source/name, destination/name
        if src.is_symlink():raise ValueError('Profile data must not contain symbolic links')
        if src.is_dir():
            shutil.copytree(src,dst,copy_function=copy_file,
                            ignore=ignore,dirs_exist_ok=True)
        elif src.is_file():copy_file(src,dst)


def remove_data(root: Path):
    for name in DATA:
        path=root/name
        if path.is_symlink() or path.is_file():path.unlink()
        elif path.is_dir():shutil.rmtree(path)
