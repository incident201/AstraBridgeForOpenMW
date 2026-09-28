import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('installer', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def archive(tmp_path, member):
    plain = tmp_path / 'test.tar.gz'
    with tarfile.open(plain, 'w:gz') as tar:
        tar.addfile(member, io.BytesIO(b'x') if member.isfile() else None)
    return plain


@pytest.mark.parametrize('name', ['/tmp/escape', '../escape', 'AstraOpenMW/../../escape', 'unexpected/file'])
def test_rejects_path_escape(tmp_path, name):
    member = tarfile.TarInfo(name); member.size = 1
    with pytest.raises(ValueError, match='Unsafe'):
        installer.extract_bundle(archive(tmp_path, member), tmp_path / 'out')
    assert not (tmp_path / 'escape').exists()


@pytest.mark.parametrize('kind', [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE])
def test_rejects_links_and_devices(tmp_path, kind):
    member = tarfile.TarInfo('AstraOpenMW/file'); member.type = kind; member.linkname = '/tmp/escape'
    with pytest.raises(ValueError, match='regular'):
        installer.extract_bundle(archive(tmp_path, member), tmp_path / 'out')


def test_valid_archive_extracts(tmp_path):
    member = tarfile.TarInfo('AstraOpenMW/engine/openmw'); member.size = 1
    installer.extract_bundle(archive(tmp_path, member), tmp_path / 'out')
    assert (tmp_path / 'out/AstraOpenMW/engine/openmw').read_bytes() == b'x'


def test_inventory_and_embedded_manifest(tmp_path):
    (tmp_path / 'engine').mkdir(); (tmp_path / 'engine/openmw').write_bytes(b'engine')
    digest = installer.sha256(tmp_path / 'engine/openmw')
    manifest = {'engine_sha256': digest, 'files': {'engine/openmw': digest}, 'asset_sha256': 'a' * 64}
    (tmp_path / 'manifest.json').write_text(json.dumps(dict(manifest, asset_sha256=None)))
    installer.verify_runtime(tmp_path, manifest)
    (tmp_path / 'engine/openmw').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='checksum'):
        installer.verify_runtime(tmp_path, manifest)
    (tmp_path / 'extra').touch()
    with pytest.raises(ValueError, match='inventory'):
        installer.verify_runtime(tmp_path, manifest)


def manifest():
    data = json.loads((ROOT / 'packaging/manifest.template.json').read_text())
    data.update(json.loads((ROOT / 'VERSION.json').read_text()), git_tag='v0.1.0', git_commit='a' * 40,
                minimum_glibc='2.17', asset_filename='runtime.tar.gz', asset_sha256='b' * 64, engine_sha256='c' * 64)
    return data


def test_wrong_version_and_host_rejected(monkeypatch):
    data = manifest()
    monkeypatch.setattr(installer.platform, 'libc_ver', lambda: ('glibc', '2.44'))
    installer.validate_manifest(data, 'v0.1.0')
    with pytest.raises(ValueError, match='requested'):
        installer.validate_manifest(data, 'v0.2.0')
    monkeypatch.setattr(installer.platform, 'libc_ver', lambda: ('glibc', '2.16'))
    with pytest.raises(ValueError, match='glibc'):
        installer.validate_manifest(data)


def test_checkout_defaults_to_exact_stable_tag(monkeypatch):
    monkeypatch.setattr(installer.subprocess, 'check_output', lambda *a, **k: 'v0.1.0\n')
    assert installer.checkout_tag() == 'v0.1.0'
    monkeypatch.setattr(installer.subprocess, 'check_output', lambda *a, **k: '')
    assert installer.checkout_tag() == 'latest'


def test_hash_failure_never_extracts_or_runs_bootstrap(tmp_path, monkeypatch):
    game = tmp_path / 'game'; game.mkdir(); (game / 'Morrowind.esm').touch()
    bundle = tmp_path / 'bundle'; bundle.mkdir()
    data = manifest(); (bundle / data['asset_filename']).write_bytes(b'corrupt')
    (bundle / 'manifest.json').write_text(json.dumps(data))
    target = tmp_path / 'runtime'
    monkeypatch.setattr(installer.platform, 'libc_ver', lambda: ('glibc', '2.44'))
    monkeypatch.setattr(installer.subprocess, 'run', lambda *a, **k: pytest.fail('must not run unverified code'))
    args = installer.argparse.Namespace(game=game, version=None, from_bundle=bundle, directory=target)
    with pytest.raises(ValueError, match='SHA256 mismatch'):
        installer.install(args)
    assert not target.exists()


def test_cpu_floor_rejects_missing_avx(monkeypatch):
    monkeypatch.setattr(installer.Path, 'read_text', lambda self: 'flags : cx16 lahf_lm popcnt pni ssse3 sse4_1 sse4_2\n')
    installer.validate_cpu('x86-64-v2')
    with pytest.raises(ValueError, match='CPU lacks'):
        installer.validate_cpu('x86-64-v3')


def test_environment_detects_modified_harness(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / 'harness'))
    from astra_bridge.environment import identity
    engine = tmp_path / 'engine/openmw'; engine.parent.mkdir(); engine.write_bytes(b'engine')
    harness = tmp_path / 'AstraBridge'; harness.mkdir(); (harness / 'astra').write_bytes(b'harness')
    data = manifest(); data['engine_sha256'] = installer.sha256(engine)
    data['files'] = {'engine/openmw': installer.sha256(engine), 'AstraBridge/astra': installer.sha256(harness / 'astra')}
    (tmp_path / 'manifest.json').write_text(json.dumps(data))
    assert identity(harness)['frozen_release']
    (harness / 'astra').write_bytes(b'changed')
    result = identity(harness)
    assert not result['frozen_release'] and result['modified_files'] == ['AstraBridge/astra']


def test_environment_records_actual_development_engine(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / 'harness'))
    from astra_bridge.environment import identity
    engine = tmp_path / 'engine/openmw'; engine.parent.mkdir(); engine.write_bytes(b'release')
    alternate = tmp_path / 'custom-openmw'; alternate.write_bytes(b'custom')
    harness = tmp_path / 'AstraBridge'; harness.mkdir()
    (harness / 'local-settings.json').write_text(json.dumps({'engine_binary': str(alternate)}))
    data = manifest(); data['engine_sha256'] = installer.sha256(engine)
    (tmp_path / 'manifest.json').write_text(json.dumps(data))
    result = identity(harness)
    assert result['actual_engine_sha256'] == installer.sha256(alternate)
    assert not result['frozen_release']


def test_gzip_extraction_needs_no_external_program(tmp_path, monkeypatch):
    member = tarfile.TarInfo('AstraOpenMW/engine/openmw'); member.size = 1
    path = archive(tmp_path, member)
    monkeypatch.setattr(installer.shutil, 'which', lambda *a: None)
    monkeypatch.setattr(installer.subprocess, 'run', lambda *a, **k: pytest.fail('external decompressor invoked'))
    installer.extract_bundle(path, tmp_path / 'out')
    assert (tmp_path / 'out/AstraOpenMW/engine/openmw').read_bytes() == b'x'
