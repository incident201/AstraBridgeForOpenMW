"""Generate a local OpenMW-only script override from the user's content files.

No game script or third-party mod is distributed. OpenMW compiles SCTX itself;
the original Morrowind executable cannot use this source-only addon.
Session enables this by default; local-settings.json may set delay_tribunal to
false for an installation deliberately managed by a different gameplay mod.
"""
from __future__ import annotations

from pathlib import Path
import re
import struct

ADDON = 'AstraTribunalDelay.omwaddon'
MARKER = b'; AstraBridge: delay Tribunal attacks until the main quest is complete'
GATE = MARKER + b'\nif ( GetJournalIndex "C3_DestroyDagoth" < 50 )\n    return\nendif\n\n'


def subrecords(data):
    offset = 0
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError('Truncated TES3 subrecord header')
        tag, size = struct.unpack_from('<4sI', data, offset)
        offset += 8
        if offset + size > len(data):
            raise ValueError('Truncated TES3 subrecord')
        yield tag, data[offset:offset + size]
        offset += size


def read_attack_script(path):
    """Read only SCPT records, seeking past all other game content."""
    result = None
    with path.open('rb') as stream:
        length = path.stat().st_size
        while header := stream.read(16):
            if len(header) != 16:
                raise ValueError(f'Truncated TES3 record header: {path.name}')
            tag, size, _, flags = struct.unpack('<4sIII', header)
            if stream.tell() + size > length:
                raise ValueError(f'Truncated TES3 record: {path.name}')
            if tag != b'SCPT':
                stream.seek(size, 1)
                continue
            parts = dict(subrecords(stream.read(size)))
            if parts.get(b'SCHD', b'')[:32].split(b'\0')[0].lower() == b'dbattackscript':
                result = flags, parts
    return result


def gate_source(source):
    """Insert before any executable statement, retaining local declarations."""
    if MARKER in source:
        raise ValueError('An already generated Tribunal script is in the input load order')
    lines = source.splitlines(keepends=True)
    began = False
    for index, line in enumerate(lines):
        code = line.split(b';', 1)[0].strip()
        if not code:
            continue
        if not began:
            if not re.fullmatch(rb'begin\s+"?dbattackscript"?', code, re.I):
                raise ValueError('Unexpected dbattackScript declaration')
            began = True
        elif not re.match(rb'(short|long|float)\s+', code, re.I):
            newline = b'\r\n' if b'\r\n' in source else b'\n'
            return b''.join(lines[:index]) + GATE.replace(b'\n', newline) + b''.join(lines[index:])
    raise ValueError('dbattackScript has no executable body')


def _sub(tag, data):
    return struct.pack('<4sI', tag, len(data)) + data


def _record(tag, data, flags=0):
    return struct.pack('<4sIII', tag, len(data), 0, flags) + data


def build_addon(script, masters, encoding='cp1252'):
    flags, parts = script
    if b'DELE' in parts or flags & 0x20:
        raise ValueError('The active dbattackScript was deleted by another plugin')
    header = bytearray(parts[b'SCHD'])
    if len(header) != 52 or not parts.get(b'SCTX'):
        raise ValueError('dbattackScript source is missing or malformed')
    source = gate_source(parts[b'SCTX'])
    struct.pack_into('<I', header, 44, 0)  # No stale vanilla bytecode.
    body = _sub(b'SCHD', header)
    if b'SCVR' in parts:
        body += _sub(b'SCVR', parts[b'SCVR'])
    body += _sub(b'SCDT', b'') + _sub(b'SCTX', source)
    file_header = _sub(b'HEDR', struct.pack('<fI32s256sI', 1.3, 0, b'AstraBridge',
                       b'Locally generated Tribunal delay. Requires OpenMW.', 1))
    for path in masters:
        file_header += _sub(b'MAST', path.name.encode(encoding) + b'\0')
        file_header += _sub(b'DATA', struct.pack('<Q', path.stat().st_size))
    return _record(b'TES3', file_header) + _record(b'SCPT', body, flags)


def _options(config):
    for line in config.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = re.sub(r'&(.)', r'\1', value[1:-1])
        yield key.strip(), value


def prepare_tribunal_delay(config, output_dir, *, base_dir, enabled=True, local_data=None):
    """Append one generated override to the harness's flat, private profile.

    The last active script definition wins, including mod overrides. Bytewise
    editing preserves localized source, variable names/order and saved locals.
    """
    if type(enabled) is not bool:
        raise ValueError('delay_tribunal must be true or false')
    options = list(_options(config))
    contents = [v for k, v in options if k == 'content' and v.casefold() != ADDON.casefold()]
    # Remove our previous generated entry if the profile is prepared again.
    def generated_entry(line):
        return any(k == 'content' and v.casefold() == ADDON.casefold() for k, v in _options(line))
    config = '\n'.join(line for line in config.splitlines() if not generated_entry(line)) + '\n'
    if not enabled or not any(v.casefold() == 'tribunal.esm' for v in contents):
        return config
    if any(k == 'config' for k, _ in options):
        raise ValueError('Tribunal delay needs the flat profile created by configure.py; nested config= is unsupported')
    directories = []
    for key, value in options:
        if key == 'data':
            path = Path(value)
            directories.append(path if path.is_absolute() else base_dir / path)
    # --data-local passed by Session overrides config and always has priority.
    local_data = local_data or dict(options).get('data-local')
    if local_data:
        path = Path(local_data)
        directories.append(path if path.is_absolute() else base_dir / path)
    # Content files live in the root of each data directory. Later data= wins.
    files = {}
    for directory in directories:
        if directory.is_dir():
            files.update((p.name.casefold(), p) for p in directory.iterdir() if p.is_file())
    masters = []
    script = None
    for name in contents:
        if Path(name).suffix.casefold() not in {'.esm', '.esp', '.omwgame', '.omwaddon'}:
            continue
        path = files.get(name.casefold())
        if path is None:
            raise ValueError(f'Tribunal delay cannot locate active content: {name}')
        masters.append(path)
        candidate = read_attack_script(path)
        if candidate is not None:
            script = candidate
    if script is None:
        raise ValueError('Active Tribunal content has no dbattackScript')
    encoding = dict(options).get('encoding', 'win1252').replace('win', 'cp')
    data = build_addon(script, masters, encoding)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / ADDON
    if not target.exists() or target.read_bytes() != data:
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(data)
        temporary.replace(target)
    return config + f'content={ADDON}\n'
