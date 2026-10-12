"""Validate an uploaded OpenMW save without loading or rewriting its game state."""
from __future__ import annotations

from pathlib import Path
import struct

from astra_bridge.protocol import BridgeError

MAX_SAVE_BYTES = 512 * 1024 * 1024
MAX_TEXT_BYTES = 64 * 1024


def validate_filename(filename):
    if (not isinstance(filename, str) or not filename
            or any(c in filename for c in '/\\\x00')
            or any(ord(c) < 32 for c in filename)):
        raise BridgeError('invalid_save_filename', message='Choose an OpenMW .omwsave file.')
    if not filename.lower().endswith('.omwsave'):
        raise BridgeError('unsupported_save_format',
                          message='Choose an OpenMW .omwsave file. Original Morrowind .ess saves require conversion first.')


def validate_save(path: Path):
    """Check record boundaries and read only the native save's public header."""
    size = path.stat().st_size
    if size > MAX_SAVE_BYTES:
        raise BridgeError('save_import_too_large', message='Save files must be no larger than 512 MiB.')
    metadata = {'bytes': size, 'content_files': [], 'player_level': 1}
    try:
        with path.open('rb') as source:
            records = 0
            required = set()
            while source.tell() < size:
                header = source.read(16)
                if len(header) != 16:
                    raise ValueError('Truncated record header')
                tag, length, _, _ = struct.unpack('<4sIII', header)
                end = source.tell() + length
                if end > size:
                    raise ValueError('Truncated record')
                if records < 2:
                    if tag != (b'TES3' if records == 0 else b'SAVE'):
                        raise ValueError('Missing OpenMW save header')
                    while source.tell() < end:
                        if end - source.tell() < 8:
                            raise ValueError('Truncated subrecord header')
                        field, count = struct.unpack('<4sI', source.read(8))
                        if source.tell() + count > end:
                            raise ValueError('Truncated subrecord')
                        wanted = ({b'FORM'} if records == 0 else {b'PLNA', b'PLLE', b'DESC', b'DEPE'})
                        if field in wanted:
                            if count > MAX_TEXT_BYTES:
                                raise ValueError('Oversized save metadata')
                            value = source.read(count)
                            if field in {b'FORM', b'PLLE'}:
                                if count != 4:
                                    raise ValueError('Invalid numeric save metadata')
                                key = 'format_version' if field == b'FORM' else 'player_level'
                                metadata[key] = struct.unpack('<I', value)[0]
                            else:
                                text = value.rstrip(b'\x00').decode('utf8', errors='replace')
                                if field == b'DEPE':
                                    metadata['content_files'].append(text)
                                else:
                                    metadata['player_name' if field == b'PLNA' else 'description'] = text
                        else:
                            source.seek(count, 1)
                        if records == 1:
                            required.add(field)
                else:
                    source.seek(length, 1)
                records += 1
            if (records < 3 or metadata.get('format_version', 0) < 2
                    or not {b'PLNA', b'PLCE', b'TSTM', b'TIME', b'DESC', b'DEPE', b'SCRN'} <= required):
                raise ValueError('Incomplete OpenMW save header')
    except (ValueError, struct.error) as exc:
        raise BridgeError('invalid_save_file',
                          message='This file is not a complete OpenMW save, or its record structure is damaged.') from exc
    return metadata
