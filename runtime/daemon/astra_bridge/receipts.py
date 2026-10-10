"""Bounded full receipts with durable protection against duplicate execution."""
import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
import uuid

from .protocol import BridgeError

LOG = logging.getLogger(__name__)


class Receipts:
    FULL_RESULT_LIMIT = 1000
    FULL_RESULT_AGE = 30 * 24 * 60 * 60
    MAINTENANCE_INTERVAL = 60
    MAINTENANCE_WRITES = 64

    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('''CREATE TABLE IF NOT EXISTS actions (
            id TEXT PRIMARY KEY, operation TEXT, args TEXT, status TEXT,
            created REAL, updated REAL, response TEXT)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS request_guards (
            id TEXT PRIMARY KEY, operation TEXT, args_hash TEXT, status TEXT,
            created REAL, updated REAL)''')
        self.db.execute('CREATE INDEX IF NOT EXISTS actions_updated ON actions(updated)')
        self.db.execute('CREATE INDEX IF NOT EXISTS actions_created ON actions(created)')
        self.db.execute('CREATE INDEX IF NOT EXISTS guards_created ON request_guards(created)')
        self.writes_since_maintenance = 0
        self.last_maintenance = time.monotonic()
        # A controller crash cannot establish whether the engine applied a mutation.
        with self.db:
            self.db.execute("UPDATE actions SET status='unknown' WHERE status='submitted'")
        self._maintain()

    @staticmethod
    def _args_hash(encoded):
        if not isinstance(encoded, str):
            # Corrupt legacy arguments must still leave a guard. No valid JSON
            # request can match this sentinel and accidentally execute again.
            return None
        return hashlib.sha256(encoded.encode('utf-8')).hexdigest()

    def begin(self, operation, args, request_id=None):
        request_id = request_id or uuid.uuid4().hex
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', request_id):
            raise BridgeError('invalid_request_id')
        encoded = json.dumps(args, sort_keys=True, ensure_ascii=False, allow_nan=False)
        with self.lock, self.db:
            old = self.db.execute('SELECT operation,args FROM actions WHERE id=?', (request_id,)).fetchone()
            if old:
                if old != (operation, encoded):
                    raise BridgeError('request_id_conflict')
                return request_id, self.get(request_id)
            guard = self.db.execute(
                'SELECT operation,args_hash FROM request_guards WHERE id=?',
                (request_id,),
            ).fetchone()
            if guard:
                if guard != (operation, self._args_hash(encoded)):
                    raise BridgeError('request_id_conflict')
                return request_id, self.get(request_id)
            now = time.time()
            self.db.execute('INSERT INTO actions VALUES (?,?,?,?,?,?,NULL)', (request_id, operation, encoded, 'submitted', now, now))
        return request_id, None

    def finish(self, request_id, response, status='completed'):
        with self.lock:
            with self.db:
                self.db.execute('UPDATE actions SET status=?,updated=?,response=? WHERE id=?',
                                (status, time.time(), json.dumps(response, ensure_ascii=False), request_id))
            self.writes_since_maintenance += 1
            if (self.writes_since_maintenance >= self.MAINTENANCE_WRITES
                    or time.monotonic() - self.last_maintenance >= self.MAINTENANCE_INTERVAL):
                self._maintain()

    def _maintain(self):
        try:
            self.prune()
        except sqlite3.Error as exc:
            # Housekeeping must not change the outcome of a committed command.
            self.last_maintenance = time.monotonic()
            self.writes_since_maintenance = 0
            LOG.warning('Unable to compact old command receipts: %s', exc)

    def prune(self):
        """Discard old payloads, never the IDs needed to prevent a repeated action.

        Maintenance is bounded per call; a large legacy store is reclaimed over
        successive calls. SQLite reuses the freed pages without a full VACUUM or
        a second database-sized allocation on an already nearly full disk.
        """
        with self.lock, self.db:
            cutoff = time.time() - self.FULL_RESULT_AGE
            rows = self.db.execute('''
                SELECT id,operation,args,status,created,updated FROM actions
                WHERE status != 'submitted' AND (
                    updated < ? OR id NOT IN (
                        SELECT id FROM actions WHERE status != 'submitted'
                        ORDER BY updated DESC, rowid DESC LIMIT ?
                    )
                ) ORDER BY updated LIMIT 1024
            ''', (cutoff, self.FULL_RESULT_LIMIT)).fetchall()
            guards = [
                (row[0], row[1], self._args_hash(row[2]), *row[3:])
                for row in rows
            ]
            self.db.executemany(
                'INSERT OR IGNORE INTO request_guards VALUES (?,?,?,?,?,?)', guards,
            )
            self.db.executemany('DELETE FROM actions WHERE id=?', ((row[0],) for row in rows))
            self.last_maintenance = time.monotonic()
            self.writes_since_maintenance = 0
            return len(rows)

    def get(self, request_id=None):
        with self.lock:
            if request_id is None:
                candidates = [
                    self.db.execute(f'SELECT id,created FROM {table} '
                                    'ORDER BY created DESC LIMIT 1').fetchone()
                    for table in ('actions', 'request_guards')
                ]
                candidates = [row for row in candidates if row is not None]
                if not candidates:
                    raise BridgeError('unknown_request_id')
                request_id = max(candidates, key=lambda row: row[1])[0]
            row = self.db.execute(
                'SELECT id,operation,status,created,updated,response FROM actions WHERE id=?',
                (request_id,),
            ).fetchone()
            retained = row is not None
            if not retained:
                row = self.db.execute('''
                    SELECT id,operation,status,created,updated,NULL
                    FROM request_guards WHERE id=?
                ''', (request_id,)).fetchone()
        if not row:
            raise BridgeError('unknown_request_id')
        result = dict(zip(('request_id','operation','status','created','updated'), row[:5]))
        if row[5]:
            result['response'] = json.loads(row[5])
        if not retained:
            result['result_retained'] = False
        return result
