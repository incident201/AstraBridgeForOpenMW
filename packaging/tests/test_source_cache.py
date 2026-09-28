import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

spec = importlib.util.spec_from_file_location('source_cache', Path(__file__).parents[1] / 'source_cache.py')
cache = importlib.util.module_from_spec(spec); spec.loader.exec_module(cache)


def test_incremental_sync_preserves_unchanged_files_and_removes_deleted_files(tmp_path):
    root = tmp_path / 'repo'; root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    source = root / 'source'; source.mkdir()
    (source / 'unchanged.cpp').write_text('keep')
    (source / 'changed.cpp').write_text('old')
    (source / 'removed.cpp').write_text('remove')
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    work = tmp_path / 'work'; work.mkdir()
    profile = {'image_id': 'old'}
    cache.prepare(root, 'source', work, profile, False)
    copy = work / 'build/openmw-openmw-0.51.0'
    before = (copy / 'unchanged.cpp').stat().st_mtime_ns
    old_digest = cache.fingerprint(root, 'source')
    (source / 'changed.cpp').write_text('new')
    (source / 'removed.cpp').unlink()
    cache.prepare(root, 'source', work, profile, True)
    assert (copy / 'unchanged.cpp').stat().st_mtime_ns == before
    assert (copy / 'changed.cpp').read_text() == 'new'
    assert not (copy / 'removed.cpp').exists()
    assert cache.fingerprint(root, 'source') != old_digest
    with pytest.raises(ValueError, match='environment'):
        cache.prepare(root, 'source', work, {'image_id': 'new'}, True)
