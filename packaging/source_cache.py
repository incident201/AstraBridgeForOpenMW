"""Incremental source synchronization; never reuse a different build environment."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def tracked(root, directory=''):
    command = ['git', '-C', str(root), 'ls-files', '-z']
    if directory: command += ['--', directory]
    output = subprocess.check_output(command)
    return [Path(name.decode()) for name in output.split(b'\0') if name and (root / name.decode()).is_file()]


def fingerprint(root, directory):
    digest = hashlib.sha256()
    for name in sorted(tracked(root, directory)):
        digest.update(name.as_posix().encode() + b'\0')
        digest.update((root / name).read_bytes())
        digest.update(b'\0')
    return digest.hexdigest()


def sync_source(root, directory, destination):
    files = {name.relative_to(directory): root / name for name in tracked(root, directory)}
    destination.mkdir(parents=True, exist_ok=True)
    for path in destination.rglob('*'):
        if path.is_file() and path.relative_to(destination) not in files:
            path.unlink()
    for name, source in files.items():
        target = destination / name
        data = source.read_bytes()
        if target.is_file() and target.read_bytes() == data:
            continue  # Preserve timestamps so Ninja does not rebuild unchanged files.
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        shutil.copymode(source, target)


def prepare(root, directory, work, profile, resume):
    source = work / 'build/openmw-openmw-0.51.0'
    receipt = work / 'build-environment.json'
    if source.exists():
        if not resume:
            raise ValueError('Work directory already has sources; use --resume or a new --work directory')
        if not receipt.exists() or json.loads(receipt.read_text()) != profile:
            raise ValueError('Build environment changed or cache has no receipt; use a new --work directory')
    receipt.write_text(json.dumps(profile, indent=2, sort_keys=True) + '\n')
    sync_source(root, directory, source)
    return source.parent


def engine_files(prefix):
    """Hash the reusable engine runtime, not disposable compiler intermediates."""
    names = [prefix / name for name in ('openmw', 'defaults.bin', 'gamecontrollerdb.txt', 'openmw.cfg')]
    if not (prefix / 'resources').is_dir():
        raise ValueError('Cached engine has no resources')
    for directory in ('resources', 'lib'):
        names.extend(p for p in (prefix / directory).rglob('*') if p.is_file())
    return {p.relative_to(prefix).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(names)}


def reusable_engine(work, inputs, profile):
    receipt_path = work / 'engine-receipt.json'
    if not receipt_path.is_file():
        return None
    try:
        receipt = json.loads(receipt_path.read_text())
        if not isinstance(receipt, dict):
            return None
        if receipt.get('build_profile') != profile or any(receipt.get(k) != v for k, v in inputs.items()):
            return None
        if receipt.get('runtime_files') != engine_files(work / 'build/engine'):
            return None
        if receipt['engine_sha256'] != receipt['runtime_files']['openmw']:
            return None
        return receipt
    except (OSError, ValueError, KeyError, TypeError):
        return None
