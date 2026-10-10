"""Bounded diagnostic files; recording and gameplay history use separate stores."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading


LOG_BYTES = 4 * 1024 * 1024
LOG_BACKUPS = 3
_write_lock = threading.RLock()


def read_tail(path: Path, max_bytes: int) -> bytes:
    with path.open('rb') as stream:
        size = stream.seek(0, os.SEEK_END)
        stream.seek(max(0, size - max_bytes))
        return stream.read(max_bytes)


def append_bounded(path: Path, data: bytes, *, max_bytes=LOG_BYTES, backups=LOG_BACKUPS):
    """Append one record and keep at most ``backups + 1`` bounded files.

    Existing oversized logs are reduced on the first write after an upgrade.
    The caller decides how to report disk failures without interrupting gameplay.
    """
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    with _write_lock:
        files = [path, *(path.with_name(f'{path.name}.{index}') for index in range(1, backups + 1))]
        for file in files:
            if file.exists() and file.stat().st_size > max_bytes:
                tail = read_tail(file, max_bytes)
                with file.open('wb') as stream:
                    stream.write(tail)
        if path.exists() and path.stat().st_size + len(data) > max_bytes:
            if backups:
                files[-1].unlink(missing_ok=True)
                for index in range(backups - 1, 0, -1):
                    if files[index].exists():
                        files[index].replace(files[index + 1])
                path.replace(files[1])
            else:
                path.unlink()
        with path.open('ab') as stream:
            stream.write(data)


def recent_events(path: Path, *, limit=200, max_bytes=256 * 1024, backups=LOG_BACKUPS):
    """Read a bounded tail across rotations, tolerating torn or malformed rows."""
    rows = []
    remaining = max_bytes
    with _write_lock:
        for index in range(backups + 1):
            file = path if index == 0 else path.with_name(f'{path.name}.{index}')
            try:
                with file.open('rb') as stream:
                    size = stream.seek(0, os.SEEK_END)
                    start = max(0, size - remaining)
                    stream.seek(start)
                    data = stream.read(remaining)
            except FileNotFoundError:
                continue
            remaining -= len(data)
            lines = data.splitlines()
            if start and lines:
                # The byte limit may begin inside an otherwise valid JSON row.
                lines = lines[1:]
            for line in reversed(lines):
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                    if len(rows) == limit:
                        return list(reversed(rows))
            if remaining <= 0:
                break
    return list(reversed(rows))
