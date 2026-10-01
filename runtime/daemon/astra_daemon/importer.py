"""Copy an installation from a tar stream into an otherwise empty managed volume."""
from pathlib import Path
import json
import shutil
import sys
import tarfile
import uuid


def import_game(source, volume: Path):
    destination=volume/'content'
    if destination.exists(): raise ValueError('Game data already exists; use a new installation.')
    stage=volume/('.import-'+uuid.uuid4().hex)
    stage.mkdir(parents=True)
    try:
        # The data filter rejects device files and paths/symlinks escaping the copy.
        with tarfile.open(fileobj=source,mode='r|*') as archive:
            for member in archive:
                archive.extract(member,stage,filter='data')
        stage.rename(destination)
    except BaseException:
        shutil.rmtree(stage)
        raise
    return {'imported':True}


if __name__=='__main__':
    print(json.dumps(import_game(sys.stdin.buffer,Path(sys.argv[1]))))
