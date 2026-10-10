import base64
import gzip
import hashlib
import json
import os
import time

import pytest

from astrabridge_runner.journal import Journal
from astrabridge_runner.locking import FileLock
from astrabridge_runner.logs import prune_sessions
from astrabridge_runner.main import main


def archive(parent, age_days):
    journal = Journal(parent)
    journal.write('manifest.json', {'schema': 1, 'provider': 'deepseek'})
    journal.api_record(1, 'request', {'body': {'goal': 'Do not truncate this archive'}})
    root = journal.root
    journal.close()
    stamp = time.time() - age_days * 86400
    for path in [*root.rglob('*'), root]:
        os.utime(path, (stamp, stamp))
    return root


def test_prune_defaults_to_preview_and_keeps_recent_sessions(tmp_path):
    old = archive(tmp_path, 60)
    recent = archive(tmp_path, 2)
    result = prune_sessions(tmp_path, keep_last=1)
    assert result['dry_run'] and [item['path'] for item in result['sessions']] == [str(old)]
    assert result['bytes'] > 0 and old.exists() and recent.exists()


def test_prune_deletes_complete_inactive_archives_only(tmp_path):
    inactive = archive(tmp_path, 60)
    active = archive(tmp_path, 60)
    unrelated = tmp_path / 'unrelated'
    unrelated.mkdir()
    (unrelated / 'manifest.json').write_text('{corrupt')
    with FileLock(active / '.session.lock', blocking=False):
        result = prune_sessions(tmp_path, keep_last=0, delete=True)
    assert result['skipped_active'] == [str(active)]
    assert not inactive.exists() and active.exists() and unrelated.exists()
    assert result['errors'] == [] and len(result['sessions']) == 1


def test_prune_skips_symlinked_archives(tmp_path):
    outside = archive(tmp_path / 'outside', 60)
    parent = tmp_path / 'sessions'
    parent.mkdir()
    (parent / 'linked').symlink_to(outside, target_is_directory=True)
    assert prune_sessions(parent, keep_last=0, delete=True)['sessions'] == []
    assert outside.exists()


@pytest.mark.parametrize('age,count', [(-1, 0), (0, -1), (float('nan'), 0), (float('inf'), 0)])
def test_prune_rejects_invalid_retention_age(tmp_path, age, count):
    with pytest.raises(ValueError):
        prune_sessions(tmp_path, older_than_days=age, keep_last=count)


def test_logs_prune_cli_does_not_require_provider_or_credentials(tmp_path, capsys):
    old = archive(tmp_path, 60)
    args = ['logs', 'prune', '--log-dir', str(tmp_path), '--keep-last', '0']
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)['dry_run'] is True and old.exists()
    assert main([*args, '--delete']) == 0
    assert json.loads(capsys.readouterr().out)['dry_run'] is False and not old.exists()


def test_model_discovery_archive_is_identified_and_locked_for_cleanup(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path))

    class API:
        def __init__(self, journal):
            self.journal = journal

        def models(self):
            parent = self.journal.root.parent
            result = prune_sessions(parent, older_than_days=0, keep_last=0, delete=True)
            assert result['sessions'] == []
            assert result['skipped_active'] == [str(self.journal.root)]
            return []

        def close(self):
            pass

    monkeypatch.setattr('astrabridge_runner.main.provider', lambda name, journal, *args: API(journal))
    assert main(['models', '--provider', 'deepseek', '--json']) == 0
    assert json.loads(capsys.readouterr().out) == []
    parent = tmp_path / 'astrabridge-runner/discovery'
    result = prune_sessions(parent, older_than_days=0, keep_last=0, delete=True)
    assert len(result['sessions']) == 1 and result['errors'] == []


def test_api_screenshots_are_stored_once_and_request_reconstruction_is_exact(tmp_path):
    journal = Journal(tmp_path)
    data = b'\x89PNG\r\n\x1a\n' + bytes(range(256)) * 4096
    image_url = 'data:image/png;base64,' + base64.b64encode(data).decode()
    digest = hashlib.sha256(data).hexdigest()
    identical_normal_text = 'astrabridge-archive://images/' + digest + '.png'
    value = {'method': 'POST', 'path': 'responses', 'body': {
        'input': [{'content': [{'type': 'input_image', 'image_url': image_url}]}],
        'text': identical_normal_text,
    }}
    try:
        first = journal.api_record(1, 'request', value)
        second = journal.api_record(2, 'request', value)
        assert len(list((journal.root / 'images').iterdir())) == 1
        assert journal.read_api_record(first) == value
        assert journal.read_api_record(second) == value
        stored = json.loads(gzip.open(journal.root / first, 'rt').read())
        assert len(json.dumps(stored)) < 2000
        assert stored['body']['input'][0]['content'][0]['image_url'] == identical_normal_text
        assert 'image_archive' not in value
    finally:
        journal.close()


def test_api_record_reader_supports_previous_inline_records_and_checks_image_integrity(tmp_path):
    journal = Journal(tmp_path)
    try:
        value = {'body': {'diagnostics': {'wall': True}}}
        record = journal.api_record(1, 'response', value)
        assert journal.read_api_record(record) == value
        data = base64.b64encode(b'image').decode()
        record = journal.api_record(2, 'request', {'body': {'image_url': 'data:image/png;base64,' + data}})
        next((journal.root / 'images').iterdir()).write_bytes(b'modified')
        with pytest.raises(ValueError, match='modified'):
            journal.read_api_record(record)
        with pytest.raises(ValueError, match='outside'):
            journal.read_api_record('../manifest.json')
    finally:
        journal.close()
