"""Durable command receipts. A duplicate request ID is never executed again."""
import json
import re
import sqlite3
import threading
import time
import uuid

from .protocol import BridgeError


class Receipts:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, operation TEXT, args TEXT, status TEXT, created REAL, updated REAL, response TEXT)')
        # A controller crash cannot establish whether the engine applied a mutation.
        with self.db:
            self.db.execute("UPDATE actions SET status='unknown' WHERE status='submitted'")

    def begin(self, operation, args, request_id=None):
        request_id = request_id or uuid.uuid4().hex
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', request_id):
            raise BridgeError('invalid_request_id')
        encoded = json.dumps(args, sort_keys=True, ensure_ascii=False, allow_nan=False)
        with self.lock, self.db:
            old = self.db.execute('SELECT operation,args FROM actions WHERE id=?', (request_id,)).fetchone()
            if old:
                if old != (operation, encoded): raise BridgeError('request_id_conflict')
                return request_id, self.get(request_id)
            now = time.time()
            self.db.execute('INSERT INTO actions VALUES (?,?,?,?,?,?,NULL)', (request_id, operation, encoded, 'submitted', now, now))
        return request_id, None

    def finish(self, request_id, response, status='completed'):
        with self.lock, self.db:
            self.db.execute('UPDATE actions SET status=?,updated=?,response=? WHERE id=?',
                            (status, time.time(), json.dumps(response, ensure_ascii=False), request_id))

    def get(self, request_id=None):
        with self.lock:
            row = self.db.execute('SELECT id,operation,status,created,updated,response FROM actions WHERE id=?', (request_id,)).fetchone() if request_id else self.db.execute('SELECT id,operation,status,created,updated,response FROM actions ORDER BY created DESC LIMIT 1').fetchone()
        if not row: raise BridgeError('unknown_request_id')
        result = dict(zip(('request_id','operation','status','created','updated'), row[:5]))
        if row[5]: result['response'] = json.loads(row[5])
        return result
