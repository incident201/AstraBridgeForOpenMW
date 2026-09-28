#!/usr/bin/env python3
"""Install a verified AstraBridge Release without compiling OpenMW (Python 3.11+)."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

REPOSITORY = 'incident201/AstraBridgeForOpenMW'
ROOT = Path(__file__).resolve().parent


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'AstraBridge-installer'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def download(url, destination):
    if not url.startswith('https://'):
        raise ValueError('Release downloads must use HTTPS')
    with urllib.request.urlopen(url, timeout=120) as response, destination.open('wb') as target:
        shutil.copyfileobj(response, target)


def checkout_tag():
    try:
        tags = subprocess.check_output(['git', '-C', str(ROOT), 'tag', '--points-at', 'HEAD'], text=True).splitlines()
        matches = [t for t in tags if re.fullmatch(r'v\d+\.\d+\.\d+', t)]
        if len(matches) == 1:
            return matches[0]
    except (OSError, subprocess.CalledProcessError):
        pass
    return 'latest'


def validate_manifest(data, requested=None):
    required = ('project_version', 'git_commit', 'git_tag', 'openmw_upstream_version',
                'protocol_version', 'platform', 'architecture', 'minimum_glibc', 'minimum_cpu_isa',
                'asset_filename', 'asset_sha256', 'engine_sha256', 'features', 'files')
    if data.get('schema_version') != 1 or any(key not in data for key in required):
        raise ValueError('Unsupported or incomplete release manifest')
    if data['platform'] != 'linux' or data['architecture'] != 'x86_64':
        raise ValueError('No compatible release for this platform')
    if not re.fullmatch(r'[0-9a-f]{40}', data['git_commit']):
        raise ValueError('Invalid environment commit')
    if requested and data['git_tag'] != requested:
        raise ValueError('Release tag differs from requested version')
    if data['git_tag'] and data['git_tag'] != 'v' + data['project_version']:
        raise ValueError('Inconsistent project version and tag')
    for key in ('asset_sha256', 'engine_sha256'):
        if not re.fullmatch(r'[0-9a-f]{64}', data[key] or ''):
            raise ValueError('Missing or invalid ' + key)
    name = data['asset_filename']
    if Path(name).name != name or not name.endswith('.tar.zst'):
        raise ValueError('Invalid release asset filename')
    validate_cpu(data['minimum_cpu_isa'])
    libc, version = platform.libc_ver()
    if libc != 'glibc' or tuple(map(int, version.split('.'))) < tuple(map(int, data['minimum_glibc'].split('.'))):
        raise ValueError('This release requires glibc >= ' + data['minimum_glibc'])


def validate_cpu(isa):
    levels = {
        'x86-64-baseline': set(),
        'x86-64-v2': {'cx16', 'lahf_lm', 'popcnt', 'pni', 'ssse3', 'sse4_1', 'sse4_2'},
        'x86-64-v3': {'avx', 'avx2', 'bmi1', 'bmi2', 'f16c', 'fma', 'abm', 'movbe', 'xsave'},
        'x86-64-v4': {'avx512f', 'avx512bw', 'avx512cd', 'avx512dq', 'avx512vl'},
    }
    if isa not in levels:
        raise ValueError('Unknown release CPU requirement: ' + str(isa))
    flags = next((set(line.split(':', 1)[1].split()) for line in Path('/proc/cpuinfo').read_text().splitlines()
                  if line.startswith('flags') and ':' in line), set())
    required = set()
    for level, features in levels.items():
        required.update(features)
        if level == isa: break
    if not required <= flags:
        raise ValueError('Release requires ' + isa + '; CPU lacks: ' + ', '.join(sorted(required - flags)))


def extract_bundle(archive, destination):
    # Decompress first, then use Python's safe extraction filter. No shell, no
    # archive-provided commands and no absolute/out-of-root/special members.
    with tempfile.TemporaryFile() as stream:
        subprocess.run(['zstd', '-q', '-d', '-c', str(archive)], stdout=stream, check=True)
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode='r:') as tar:
            for member in tar.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'AstraOpenMW':
                    raise ValueError('Unsafe archive member: ' + member.name)
                if not (member.isfile() or member.isdir()):
                    raise ValueError('Release archives must contain regular files/directories only')
            tar.extractall(destination, filter='data')


def verify_runtime(runtime, manifest):
    inner = json.loads((runtime / 'manifest.json').read_text())
    expected = dict(manifest, asset_sha256=None)
    if inner != expected:
        raise ValueError('Embedded manifest differs from release manifest')
    actual_files = {p.relative_to(runtime).as_posix() for p in runtime.rglob('*') if p.is_file()}
    if actual_files != set(manifest['files']) | {'manifest.json'}:
        raise ValueError('Runtime file inventory differs from manifest')
    for name, digest in manifest['files'].items():
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or sha256(runtime / name) != digest:
            raise ValueError('Runtime checksum mismatch: ' + name)
    if sha256(runtime / 'engine/openmw') != manifest['engine_sha256']:
        raise ValueError('Engine checksum mismatch')


def install(args):
    if sys.version_info < (3, 11):
        raise ValueError('Python >= 3.11 is required')
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        raise ValueError('Published runtimes currently target Linux x86_64')
    if not shutil.which('zstd'):
        raise ValueError('Install the zstd command before running the installer')
    game = args.game.expanduser().resolve()
    data = game / 'Data Files' if (game / 'Data Files').is_dir() else game
    if not data.is_dir() or not any(p.name.lower() == 'morrowind.esm' for p in data.iterdir()):
        raise ValueError('Supply a Morrowind installation containing Data Files/Morrowind.esm')
    selected = args.version or ('latest' if args.from_bundle else checkout_tag())
    if args.from_bundle:
        bundle = args.from_bundle.expanduser().resolve()
        manifest = json.loads((bundle / 'manifest.json').read_text())
        requested = None
    else:
        if selected != 'latest' and not re.fullmatch(r'v\d+\.\d+\.\d+', selected):
            raise ValueError('Use --version latest or vX.Y.Z, or --from-bundle for development')
        endpoint = 'latest' if selected == 'latest' else 'tags/' + selected
        release = read_json(f'https://api.github.com/repos/{REPOSITORY}/releases/{endpoint}')
        if release['draft'] or release['prerelease']:
            raise ValueError('Requested release is not stable')
        requested = release['tag_name']
        assets = {item['name']: item['browser_download_url'] for item in release['assets']}
        if 'manifest.json' not in assets:
            raise ValueError('Release has no manifest.json')
        manifest = read_json(assets['manifest.json'])
    validate_manifest(manifest, requested)
    target = (args.directory or Path.home() / 'AstraOpenMW' / (manifest['git_tag'] or ('dev-' + manifest['git_commit'][:12]))).expanduser().resolve()
    if target.exists():
        raise ValueError(f'Destination exists: {target}; choose --directory to preserve existing saves/config')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.astra-install-', dir=target.parent) as temporary:
        stage = Path(temporary)
        archive = stage / manifest['asset_filename']
        if args.from_bundle:
            shutil.copyfile(bundle / archive.name, archive)
        else:
            if archive.name not in assets:
                raise ValueError('Release asset missing: ' + archive.name)
            download(assets[archive.name], archive)
        if sha256(archive) != manifest['asset_sha256']:
            raise ValueError('Release archive SHA256 mismatch; nothing installed')
        extract_bundle(archive, stage)
        runtime = stage / 'AstraOpenMW'
        verify_runtime(runtime, manifest)
        (runtime / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        runtime.rename(target)
    # Configure after relocation so every generated absolute path is final.
    harness = target / 'AstraBridge'
    subprocess.run([sys.executable, str(harness / 'configure.py'), '--data', str(game),
                    '--recordings', str(target / 'recordings'), '--encoding', args.encoding], check=True)
    subprocess.run([sys.executable, str(harness / 'bootstrap.py'), '--offline'], check=True)
    skill = target / 'skill/openmw-play'
    (skill / 'installation.json').write_text(json.dumps({'ASTRA_HOME': str(harness),
        'manifest': str(target / 'manifest.json')}, indent=2) + '\n')
    if args.skill_dir:
        destination = args.skill_dir.expanduser().resolve()
        if destination.exists():
            raise ValueError(f'Skill destination already exists: {destination}; installed skill remains at {skill}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill, destination)
        skill = destination
    result = subprocess.run([str(harness / '.venv/bin/python'), str(harness / 'doctor.py')])
    print(f'Runtime: {target}\nSkill: {skill / "SKILL.md"}\nASTRA_HOME={harness}', flush=True)
    if result.returncode:
        raise ValueError('Runtime installed, but doctor found problems; fix them before playing (see above)')
    print('Ready. Give the installed skill to your agent, then run AstraBridge/astra start.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--version', help='latest or vX.Y.Z; default: checkout tag, otherwise latest stable')
    source.add_argument('--from-bundle', type=Path, help='Explicit local release/development assets directory')
    parser.add_argument('--directory', type=Path, help='New private installation directory')
    parser.add_argument('--skill-dir', type=Path, help='Also install skill into a new agent skill directory')
    parser.add_argument('--encoding', choices=['win1250', 'win1251', 'win1252'], default='win1251')
    try:
        install(parser.parse_args())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        parser.exit(1, f'Installation failed: {exc}\n')


if __name__ == '__main__':
    main()
