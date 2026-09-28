"""Public environment identity; contains no game state."""
import hashlib
import json
import subprocess
from pathlib import Path


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def engine_path(installation):
    installation = Path(installation)
    modern = installation / 'engine/openmw'
    if modern.is_file():
        return modern
    legacy = sorted(installation.glob('openmw-*/openmw.x86_64'))
    if len(legacy) == 1:
        return legacy[0]
    raise ValueError('Missing engine/openmw; install the matching Release with install.py')


def identity(root):
    root = Path(root)
    installation = root.parent
    manifest = installation / 'manifest.json'
    if manifest.is_file():
        data = json.loads(manifest.read_text())
        keys = ('project_version', 'protocol_version', 'git_commit', 'git_tag',
                'engine_sha256', 'asset_sha256', 'platform', 'architecture')
        result = {key: data.get(key) for key in keys}
        local = root / 'local-settings.json'
        settings = json.loads(local.read_text()) if local.exists() else {}
        engine = Path(settings['engine_binary']) if settings.get('engine_binary') else engine_path(installation)
        result['runtime_overrides'] = {key: settings[key] for key in ('engine_binary', 'engine_libraries') if settings.get(key)}
        result['actual_engine_sha256'] = sha256(engine)
        result['engine_matches_manifest'] = result['actual_engine_sha256'] == data['engine_sha256']
        result['modified_files'] = [name for name, digest in data.get('files', {}).items()
                                    if not (installation / name).is_file() or sha256(installation / name) != digest]
        result['frozen_release'] = bool(data.get('git_tag')) and result['engine_matches_manifest'] and not result['modified_files'] and not result['runtime_overrides']
        return result
    version = installation / 'VERSION.json'
    result = json.loads(version.read_text()) if version.exists() else {}
    result['frozen_release'] = False
    try:
        result['git_commit'] = subprocess.check_output(
            ['git', '-C', str(installation), 'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        result['git_commit'] = None
    return result
