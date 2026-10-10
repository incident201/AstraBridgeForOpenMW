import json
import sqlite3
from types import SimpleNamespace

import pytest

from astra_bridge.control import Control
from astra_bridge.information import receipt_details
from astra_bridge.protocol import BridgeError
from astra_bridge.receipts import Receipts


def complete(store, request_id, value=None):
    store.begin('use_item', {'ref': 'item_1'}, request_id)
    store.finish(request_id, value or {'action': {'submitted': True}})


def test_expired_receipt_cannot_execute_again_or_change_arguments(tmp_path, monkeypatch):
    monkeypatch.setattr(Receipts, 'FULL_RESULT_LIMIT', 2)
    calls = []
    session = SimpleNamespace(
        inbox=tmp_path / 'inbox.json', runtime=tmp_path,
        latest_observation=None, uncertain=False,
        call=lambda op, args: calls.append(op) or {'action': {'submitted': True}},
    )
    control = Control(session)
    for index in range(5):
        control.execute('use_item', {'ref': 'item_1', 'request_id': f'consume-{index}'})
    assert control.receipts.prune() == 3
    result = control.execute('use_item', {'ref': 'item_1', 'request_id': 'consume-0'})
    assert result['status'] == 'completed'
    assert result['result_retained'] is False
    assert 'response' not in result
    assert len(calls) == 5
    with pytest.raises(BridgeError, match='request_id_conflict'):
        control.execute('use_item', {'ref': 'item_2', 'request_id': 'consume-0'})
    assert control.receipts.get()['request_id'] == 'consume-4'


def test_old_and_unknown_payloads_expire_but_pending_receipt_survives(tmp_path):
    store = Receipts(tmp_path / 'receipts.db')
    complete(store, 'finished')
    store.begin('use_item', {'ref': 'item_1'}, 'uncertain')
    store.finish('uncertain', {'error': 'result_unknown'}, 'unknown')
    store.begin('use_item', {'ref': 'item_1'}, 'pending')
    with store.db:
        store.db.execute('UPDATE actions SET updated=0')
    assert store.prune() == 2
    assert store.get('finished')['result_retained'] is False
    assert store.get('uncertain')['status'] == 'unknown'
    assert store.get('pending')['status'] == 'submitted'
    assert 'result_retained' not in store.get('pending')


def test_compact_guards_persist_across_restart_with_canonical_unicode_arguments(tmp_path):
    path = tmp_path / 'receipts.db'
    store = Receipts(path)
    store.begin('save', {'description': 'Привет', 'other': 1}, 'unicode')
    store.finish('unicode', {'saved': True})
    with store.db:
        store.db.execute('UPDATE actions SET updated=0')
    store.prune()
    store.db.close()
    restarted = Receipts(path)
    _, previous = restarted.begin('save', {'other': 1, 'description': 'Привет'}, 'unicode')
    assert previous['status'] == 'completed'
    assert previous['result_retained'] is False
    assert restarted.get()['request_id'] == 'unicode'


def test_periodic_cleanup_bounds_large_payloads_and_reuses_database_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(Receipts, 'FULL_RESULT_LIMIT', 3)
    monkeypatch.setattr(Receipts, 'MAINTENANCE_WRITES', 2)
    store = Receipts(tmp_path / 'receipts.db')
    payload = {'data': 'x' * 16000}
    for index in range(40):
        complete(store, f'action-{index}', payload)
    store.prune()
    assert store.db.execute('SELECT count(*) FROM actions').fetchone()[0] == 3
    assert store.db.execute('SELECT count(*) FROM request_guards').fetchone()[0] == 37
    assert store.db.execute('PRAGMA freelist_count').fetchone()[0] > 0
    assert store.get('action-39')['response'] == payload


def test_migrates_old_database_and_preserves_unknown_execution_status(tmp_path, monkeypatch):
    monkeypatch.setattr(Receipts, 'FULL_RESULT_LIMIT', 1)
    path = tmp_path / 'receipts.db'
    with sqlite3.connect(path) as db:
        db.execute('''CREATE TABLE actions (id TEXT PRIMARY KEY, operation TEXT,
            args TEXT, status TEXT, created REAL, updated REAL, response TEXT)''')
        db.execute('INSERT INTO actions VALUES (?,?,?,?,?,?,?)',
                   ('old', 'use_item', '{}', 'completed', 1, 1, json.dumps({'old': True})))
        db.execute('INSERT INTO actions VALUES (?,?,?,?,?,?,?)',
                   ('crashed', 'use_item', '{}', 'submitted', 2, 2, None))
    store = Receipts(path)
    assert store.get('old')['status'] == 'completed'
    assert store.get('old')['result_retained'] is False
    assert store.begin('use_item', {}, 'crashed')[1]['status'] == 'unknown'
    assert store.begin('use_item', {}, 'old')[1]['result_retained'] is False


def test_expired_details_return_explicit_error():
    receipt = {'request_id': 'old', 'status': 'completed', 'result_retained': False}
    with pytest.raises(BridgeError, match='action_result_expired') as exc:
        receipt_details(receipt, {'section': 'summary'})
    assert exc.value.details['request_id'] == 'old'


def test_cleanup_error_cannot_turn_committed_result_into_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(Receipts, 'MAINTENANCE_WRITES', 1)
    store = Receipts(tmp_path / 'receipts.db')

    def unavailable():
        raise sqlite3.OperationalError('database or disk is full')

    monkeypatch.setattr(store, 'prune', unavailable)
    complete(store, 'successful')
    assert store.get('successful')['response']['action']['submitted']
    assert store.get('successful')['status'] == 'completed'


@pytest.mark.parametrize('arguments', [None, b'not-json'])
def test_corrupt_legacy_arguments_keep_nonmatching_guard(tmp_path, arguments):
    store = Receipts(tmp_path / 'receipts.db')
    with store.db:
        store.db.execute('INSERT INTO actions VALUES (?,?,?,?,?,?,NULL)',
                         ('corrupt', 'use_item', arguments, 'unknown', 1, 1))
    assert store.prune() == 1
    assert store.get('corrupt')['status'] == 'unknown'
    with pytest.raises(BridgeError, match='request_id_conflict'):
        store.begin('use_item', {}, 'corrupt')
