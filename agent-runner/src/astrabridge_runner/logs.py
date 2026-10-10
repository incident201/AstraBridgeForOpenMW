"""Host-controlled cleanup of complete inactive session archives."""

import json
import math
import os
import shutil
import time
from pathlib import Path

from .locking import FileLock


def session_metadata(path):
    if path.is_symlink() or not path.is_dir():
        return None
    manifest = path / 'manifest.json'
    if manifest.is_symlink():
        return None
    try:
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('schema') != 1 or data.get('provider') not in ('deepseek', 'openai'):
            return None
        # Event and state writes refresh these times throughout a run. API
        # archives need not be read to establish the session's latest activity.
        stamps = [manifest.stat().st_mtime]
        for name in ('events.jsonl', 'active-state.json'):
            file = path / name
            if file.exists() and not file.is_symlink():
                stamps.append(file.stat().st_mtime)
        return {'path': str(path), 'last_activity': max(stamps)}
    except (OSError, ValueError, AttributeError):
        return None


def directory_bytes(path):
    total = 0
    for directory, _, names in os.walk(path, followlinks=False):
        for name in names:
            total += (Path(directory) / name).lstat().st_size
    return total


def prune_sessions(parent, *, older_than_days=30, keep_last=5, delete=False):
    """Prune whole archives; active journals and unrelated files are preserved."""
    if not math.isfinite(older_than_days) or older_than_days < 0 or keep_last < 0:
        raise ValueError('Log retention age and keep count must be nonnegative.')
    parent = Path(parent).resolve()
    result = {
        'log_directory': str(parent), 'dry_run': not delete,
        'sessions': [], 'skipped_active': [], 'errors': [], 'bytes': 0,
    }
    if not parent.exists():
        return result
    cutoff = time.time() - older_than_days * 86400
    # New sessions and resumes take this same short-lived coordination lock
    # before their lifetime lock. An inactive archive cannot be resumed during
    # the gap between releasing its lock and deleting its directory on Windows.
    with FileLock(parent / '.create.lock', blocking=False):
        sessions = [item for path in parent.iterdir() if (item := session_metadata(path))]
        sessions.sort(key=lambda item: item['last_activity'], reverse=True)
        for item in sessions[keep_last:]:
            if item['last_activity'] >= cutoff:
                continue
            path = Path(item['path'])
            lock = FileLock(path / '.session.lock', blocking=False)
            try:
                lock.__enter__()
            except RuntimeError:
                result['skipped_active'].append(str(path))
                continue
            try:
                size = directory_bytes(path)
            except OSError as exc:
                result['errors'].append({'path': str(path), 'message': str(exc)})
                continue
            finally:
                lock.__exit__()
            try:
                if delete:
                    shutil.rmtree(path)
                result['sessions'].append({**item, 'bytes': size})
                result['bytes'] += size
            except OSError as exc:
                result['errors'].append({'path': str(path), 'message': str(exc)})
    return result
