import importlib.util
import hashlib
import http.client
import io
import json
from pathlib import Path
import ssl
import subprocess
import tarfile
import urllib.error

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
    version = json.loads((ROOT / 'VERSION.json').read_text())
    data.update(version, git_tag='v' + version['project_version'], git_commit='a' * 40,
                minimum_glibc='2.17', asset_filename='runtime.tar.gz', asset_sha256='b' * 64, engine_sha256='c' * 64)
    return data


def test_wrong_version_and_host_rejected(monkeypatch):
    data = manifest()
    monkeypatch.setattr(installer.platform, 'libc_ver', lambda: ('glibc', '2.44'))
    installer.validate_manifest(data, data['git_tag'])
    with pytest.raises(ValueError, match='requested'):
        installer.validate_manifest(data, 'v999.999.999')
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


def test_capture_library_prefers_bundle_over_system(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / 'harness'))
    from astra_bridge.environment import native_library
    name='libxcb-composite.so.0'
    assert native_library(name,tmp_path)==name
    library=tmp_path/'engine/lib'/name;library.parent.mkdir(parents=True);library.touch()
    assert native_library(name,tmp_path)==str(library)


class Response(io.BytesIO):
    def __init__(self, body, length=None):
        super().__init__(body)
        self.headers = {'Content-Length': str(len(body) if length is None else length)}


def fetch(kind, tmp_path):
    url = 'https://github.com/example/repository/releases/download/v1.2.3/test'
    if kind == 'json':
        return installer.read_json(url)
    path = tmp_path / 'download'
    installer.download(url, path)
    return path.read_bytes()


@pytest.mark.parametrize('kind', ['json', 'archive'])
@pytest.mark.parametrize('code', [429, 500, 502, 503, 504])
def test_transient_http_failures_retry_with_bounded_exponential_backoff(tmp_path, monkeypatch, kind, code):
    calls = []; sleeps = []
    def open_url(request, **kwargs):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, code, 'temporary', {}, None)
    monkeypatch.setattr(installer.urllib.request, 'urlopen', open_url)
    monkeypatch.setattr(installer.time, 'sleep', sleeps.append)
    with pytest.raises(urllib.error.HTTPError):
        fetch(kind, tmp_path)
    assert len(calls) == 4 and sleeps == [1, 2, 4]


@pytest.mark.parametrize('kind', ['json', 'archive'])
@pytest.mark.parametrize('code', [404, 403])
def test_permanent_http_errors_are_not_retried(tmp_path, monkeypatch, kind, code):
    calls = []
    def open_url(request, **kwargs):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, code, 'missing or forbidden', {}, None)
    monkeypatch.setattr(installer.urllib.request, 'urlopen', open_url)
    monkeypatch.setattr(installer.time, 'sleep', lambda _: pytest.fail('must not retry'))
    with pytest.raises(urllib.error.HTTPError):
        fetch(kind, tmp_path)
    assert len(calls) == 1


@pytest.mark.parametrize('kind', ['json', 'archive'])
@pytest.mark.parametrize('error', [urllib.error.URLError('DNS lookup failed'), TimeoutError('timed out'),
                                  ConnectionResetError('reset'), ssl.SSLEOFError('TLS connection interrupted'),
                                  http.client.IncompleteRead(b'partial', 10)])
def test_network_failures_can_recover(tmp_path, monkeypatch, kind, error):
    calls = []; sleeps = []
    body = b'{"complete":true}'
    def open_url(request, **kwargs):
        calls.append(request.full_url)
        assert request.get_header('Authorization') is None
        if len(calls) < 3:
            raise error
        return Response(body)
    monkeypatch.setattr(installer.urllib.request, 'urlopen', open_url)
    monkeypatch.setattr(installer.time, 'sleep', sleeps.append)
    assert fetch(kind, tmp_path) == ({'complete': True} if kind == 'json' else body)
    assert len(calls) == 3 and sleeps == [1, 2]


def test_manifest_read_failure_retries_the_whole_response(tmp_path, monkeypatch):
    class InterruptedJSON(Response):
        def read(self, *args):
            raise http.client.IncompleteRead(b'{"complete":', 5)
    broken = InterruptedJSON(b'')
    responses = [broken, Response(b'{"complete":true}')]
    monkeypatch.setattr(installer.urllib.request, 'urlopen', lambda *a, **k: responses.pop(0))
    sleeps = []; monkeypatch.setattr(installer.time, 'sleep', sleeps.append)
    assert fetch('json', tmp_path) == {'complete': True}
    assert broken.closed and not responses and sleeps == [1]


@pytest.mark.parametrize('disconnect', [False, True])
def test_interrupted_archive_is_restarted_without_partial_prefix(tmp_path, monkeypatch, disconnect):
    class BrokenResponse(Response):
        def read(self, *args):
            if self.tell() and disconnect:
                raise ConnectionResetError('transfer interrupted')
            return super().read(*args)
    responses = [BrokenResponse(b'partial bytes', length=100), Response(b'complete archive')]
    monkeypatch.setattr(installer.urllib.request, 'urlopen', lambda *a, **k: responses.pop(0))
    sleeps = []; monkeypatch.setattr(installer.time, 'sleep', sleeps.append)
    assert fetch('archive', tmp_path) == b'complete archive'
    assert not responses and sleeps == [1]


def test_local_write_errors_and_invalid_json_are_not_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.urllib.request, 'urlopen', lambda *a, **k: Response(b'not json'))
    monkeypatch.setattr(installer.time, 'sleep', lambda _: pytest.fail('must not retry'))
    with pytest.raises(FileNotFoundError):
        installer.download('https://github.com/test', tmp_path / 'missing-parent/file')
    with pytest.raises(json.JSONDecodeError):
        installer.read_json('https://github.com/test')


def release_bundle(tmp_path):
    data = manifest()
    data['asset_filename'] = f'astrabridge-openmw-{data["git_tag"]}-linux-x86_64.tar.gz'
    files = {'engine/openmw': b'engine', 'python/bin/python3': b'python',
             'AstraBridge/configure.py': b'configure', 'AstraBridge/bootstrap.py': b'bootstrap',
             'AstraBridge/doctor.py': b'doctor', 'skill/openmw-play/SKILL.md': b'skill'}
    data['files'] = {name: hashlib.sha256(body).hexdigest() for name, body in files.items()}
    data['engine_sha256'] = data['files']['engine/openmw']
    files['manifest.json'] = json.dumps(dict(data, asset_sha256=None)).encode()
    archive = tmp_path / data['asset_filename']
    with tarfile.open(archive, 'w:gz') as tar:
        for name, body in files.items():
            info = tarfile.TarInfo('AstraOpenMW/' + name); info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    data['asset_sha256'] = installer.sha256(archive)
    return data, archive.read_bytes()


def install_args(tmp_path, selected):
    game = tmp_path / 'game'; game.mkdir(); (game / 'Morrowind.esm').touch()
    return installer.argparse.Namespace(game=game, version=selected, from_bundle=None,
                                        directory=tmp_path / 'installed', skill_dir=None, encoding='win1251')


@pytest.mark.parametrize('selection', ['latest', 'version'])
def test_direct_release_install_pins_archive_to_verified_manifest(tmp_path, monkeypatch, selection):
    data, archive = release_bundle(tmp_path)
    tag = data['git_tag']; base = f'https://github.com/{installer.REPOSITORY}/releases/'
    manifest_url = base + ('latest/download/' if selection == 'latest' else f'download/{tag}/') + 'manifest.json'
    archive_url = base + f'download/{tag}/' + data['asset_filename']
    calls = []; commands = []
    def open_url(request, **kwargs):
        calls.append(request.full_url)
        assert request.get_header('Authorization') is None
        if request.full_url == manifest_url:
            return Response(json.dumps(data).encode())
        assert request.full_url == archive_url, 'only direct GitHub release downloads are allowed'
        return Response(archive)
    monkeypatch.setattr(installer.urllib.request, 'urlopen', open_url)
    monkeypatch.setattr(installer.subprocess, 'run', lambda cmd, **kwargs: commands.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    args = install_args(tmp_path, 'latest' if selection == 'latest' else tag)
    installer.install(args)
    assert calls == [manifest_url, archive_url]
    assert json.loads((args.directory / 'manifest.json').read_text()) == data
    assert (args.directory / 'engine/openmw').read_bytes() == b'engine'
    assert commands[0][2:] == ['--data', str(args.game), '--recordings', str(args.directory / 'recordings'), '--encoding', 'win1251']
    assert commands[1][-1] == '--offline' and commands[2][-1].endswith('/doctor.py')
    assert json.loads((args.directory / 'skill/openmw-play/installation.json').read_text())['ASTRA_HOME'] == str(args.directory / 'AstraBridge')
    assert not list(tmp_path.glob('.astra-install-*'))


@pytest.mark.parametrize('bad', ['wrong_tag', 'missing_tag', 'archive_hash', 'runtime_hash', 'embedded_manifest'])
def test_direct_downloads_preserve_release_verification(tmp_path, monkeypatch, bad):
    data, archive = release_bundle(tmp_path)
    selected = data['git_tag']; expected = 'requested'
    if bad == 'wrong_tag':
        selected = 'v999.999.999'
    elif bad == 'missing_tag':
        selected = 'latest'; data['git_tag'] = None; expected = 'Invalid release tag'
    elif bad == 'archive_hash':
        archive = b'corrupt archive'; expected = 'SHA256 mismatch'
    else:
        members = {}
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
            for info in tar.getmembers():
                members[info.name] = tar.extractfile(info).read()
        if bad == 'runtime_hash':
            members['AstraOpenMW/engine/openmw'] = b'tampered engine'; expected = 'checksum'
        else:
            members['AstraOpenMW/manifest.json'] = b'{}'; expected = 'Embedded manifest'
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as tar:
            for name, body in members.items():
                info = tarfile.TarInfo(name); info.size = len(body); tar.addfile(info, io.BytesIO(body))
        archive = buffer.getvalue(); data['asset_sha256'] = hashlib.sha256(archive).hexdigest()
    calls = []
    def open_url(request, **kwargs):
        calls.append(request.full_url)
        return Response(json.dumps(data).encode() if request.full_url.endswith('/manifest.json') else archive)
    monkeypatch.setattr(installer.urllib.request, 'urlopen', open_url)
    monkeypatch.setattr(installer.subprocess, 'run', lambda *a, **k: pytest.fail('must not configure unverified files'))
    args = install_args(tmp_path, selected)
    with pytest.raises(ValueError, match=expected):
        installer.install(args)
    assert len(calls) == (1 if bad in {'wrong_tag', 'missing_tag'} else 2)
    assert not args.directory.exists() and not list(tmp_path.glob('.astra-install-*'))
