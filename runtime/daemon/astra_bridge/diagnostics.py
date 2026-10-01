"""On-demand, read-only checks of automatically prepared fixes.

These describe files on disk, not the state of a running engine. No save,
navigation cache, or spatial-memory database is opened.
"""
import configparser
import json
from pathlib import Path

from .tribunal import ADDON, GATE, _options, read_attack_script


def _text(path):
    return path.read_text() if path.is_file() else ''


def _files(config, base, local_data):
    directories = [Path(v) for k, v in _options(config) if k == 'data']
    directories.append(local_data)  # Session's --data-local wins.
    result = {}
    for directory in directories:
        if not directory.is_absolute():
            directory = base / directory
        if directory.is_dir():
            result.update((p.name.casefold(), p) for p in directory.iterdir() if p.is_file())
    return result


def _tribunal(root, config, profile, local):
    enabled = local.get('delay_tribunal', True)
    if type(enabled) is not bool:
        raise ValueError('delay_tribunal must be true or false')
    result = {'requested_enabled': enabled, 'condition': 'C3_DestroyDagoth >= 50'}
    contents = [v.casefold() for k, v in _options(profile) if k == 'content']
    if not enabled:
        if ADDON.casefold() in contents:
            return {**result, 'status': 'pending_start', 'reason': 'disabled on next astra start'}
        return {**result, 'status': 'disabled'}
    if any(k == 'config' for k, _ in _options(config)):
        return {**result, 'status': 'unverified', 'reason': 'nested_config'}
    if not any(k == 'content' and v.casefold() == 'tribunal.esm' for k, v in _options(config)):
        if ADDON.casefold() in contents:
            return {**result, 'status': 'pending_start', 'reason': 'Tribunal removed from next-start content'}
        return {**result, 'status': 'not_applicable', 'reason': 'Tribunal.esm is not enabled'}
    result['addon'] = ADDON
    if ADDON.casefold() not in contents:
        return {**result, 'status': 'pending_start', 'reason': 'generated on next astra start'}
    files = _files(profile, root / 'runtime/profile', root / 'runtime/local-data')
    path = files.get(ADDON.casefold())
    script = read_attack_script(path) if path else None
    if not script or script[0] & 0x20 or b'DELE' in script[1] or GATE not in script[1].get(b'SCTX', b'').replace(b'\r\n', b'\n'):
        return {**result, 'status': 'needs_prepare', 'reason': 'generated script is missing or does not contain the gate'}
    for name in contents[contents.index(ADDON.casefold()) + 1:]:
        if Path(name).suffix not in {'.esm', '.esp', '.omwgame', '.omwaddon'}:
            continue
        path = files.get(name)
        if path is None:
            return {**result, 'status': 'unverified', 'reason': f'cannot locate later content: {name}'}
        if read_attack_script(path) is not None:
            return {**result, 'status': 'overridden', 'by': path.name}
    return {**result, 'status': 'configured'}


def inspect_auto_fixes(root):
    root = Path(root)
    fixes = {}
    try:
        config = _text(root.parent / 'config/openmw.cfg')
        profile = _text(root / 'runtime/profile/openmw.cfg')
        local = json.loads(_text(root / 'local-settings.json') or '{}')
        if not isinstance(local, dict):
            raise ValueError('local-settings.json must contain an object')
        fixes['tribunal_delay'] = _tribunal(root, config, profile, local)
    except (OSError, ValueError) as exc:
        fixes['tribunal_delay'] = {'status': 'error', 'reason': str(exc)}
    try:
        settings = configparser.ConfigParser(interpolation=None, strict=False)
        settings.read_string(_text(root / 'runtime/profile/settings.cfg'))
        names = ('xbase_anim', 'xbase_anim_female', 'xbase_animkna')
        present = sum((root / 'mod/Animations' / name / '_xYAIAF.kf').is_file() for name in names)
        enabled = settings.getboolean('Game', 'use additional anim sources', fallback=False)
        configured_data = [Path(v) for k, v in _options(_text(root / 'runtime/profile/openmw.cfg')) if k == 'data']
        bundled_data = any((p if p.is_absolute() else root / 'runtime/profile' / p).resolve() == (root / 'mod').resolve()
                           for p in configured_data)
        fixes['npc_idle_drift'] = {
            'status': 'missing_assets' if present != len(names) else 'configured' if enabled and bundled_data else 'pending_start',
            'assets_present': present, 'assets_expected': len(names),
            'additional_animation_sources': enabled, 'bundled_data_configured': bundled_data,
        }
        threads = settings.getint('Physics', 'async num threads', fallback=None)
        fixes['pause_physics'] = {'status': 'configured' if threads == 0 else 'pending_start',
                                  'async_threads': threads}
    except (OSError, ValueError, configparser.Error) as exc:
        for name in ('npc_idle_drift', 'pause_physics'):
            fixes[name] = {'status': 'error', 'reason': str(exc)}
    return {'scope': 'profile_on_disk', 'fixes': fixes}
