import importlib.util
import json
import hashlib
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


def test_cached_engine_requires_matching_native_inputs_environment_and_every_runtime_file(tmp_path):
    prefix = tmp_path / 'build/engine'; (prefix / 'resources').mkdir(parents=True)
    for name in ('openmw', 'defaults.bin', 'gamecontrollerdb.txt', 'openmw.cfg', 'resources/shader'):
        (prefix / name).write_bytes(name.encode())
    inputs = {'source_tree':'source', 'native_tree':'native', 'source_digest':'src-hash', 'native_digest':'native-hash'}
    profile = {'image_id':'builder-1', 'container_recipe':'recipe', 'portable_deps':True}
    receipt = {**inputs, 'build_profile':profile, 'runtime_files':cache.engine_files(prefix),
               'engine_sha256':hashlib.sha256(b'openmw').hexdigest(), 'build_commit':'old-python-release'}
    path = tmp_path / 'engine-receipt.json'; path.write_text(json.dumps(receipt))
    assert cache.reusable_engine(tmp_path, inputs, profile) == receipt
    for key in inputs:
        assert cache.reusable_engine(tmp_path, {**inputs,key:'changed'}, profile) is None
    assert cache.reusable_engine(tmp_path, inputs, {**profile,'image_id':'new-builder'}) is None
    for name in ('openmw','resources/shader','defaults.bin'):
        file = prefix / name; original = file.read_bytes(); file.write_bytes(b'corrupt')
        assert cache.reusable_engine(tmp_path, inputs, profile) is None
        file.write_bytes(original)
    extra = prefix / 'resources/extra'; extra.touch()
    assert cache.reusable_engine(tmp_path, inputs, profile) is None
    extra.unlink(); (prefix / 'resources/shader').unlink()
    assert cache.reusable_engine(tmp_path, inputs, profile) is None
    path.write_text('[]')
    assert cache.reusable_engine(tmp_path, inputs, profile) is None
    path.write_text('broken json')
    assert cache.reusable_engine(tmp_path, inputs, profile) is None
