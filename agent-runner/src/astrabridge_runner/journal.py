import gzip
import json
import os
import time
import uuid
from pathlib import Path


def json_text(value): return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def atomic_json(path, value):
    path = Path(path); temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(json_text(value)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally: temporary.unlink(missing_ok=True)


class Journal:
    def __init__(self, parent, secret='', *, resume=None):
        self.root = Path(resume).resolve() if resume else Path(parent).resolve() / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
        self.root.mkdir(parents=True, mode=0o700, exist_ok=bool(resume))
        self.secrets = set(); self.add_secret(secret)
        for name in ('api', 'images'): (self.root / name).mkdir(mode=0o700, exist_ok=bool(resume))
        self.sequence = 0
        self.api_sequence = max([int(p.name.split('-')[0]) for p in (self.root / 'api').glob('*.json.gz')] or [0])
        events = self.root / 'events.jsonl'
        if resume:
            data = events.read_bytes()
            if data and not data.endswith(b'\n'):
                split=data.rfind(b'\n')+1
                fragment=self.root/('events-incomplete-'+uuid.uuid4().hex+'.log')
                fd=os.open(fragment,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as stream:stream.write(data[split:])
                data = data[:split]
                with events.open('wb') as stream: stream.write(data)
            rows = [json.loads(line) for line in data.splitlines()]
            self.sequence = rows[-1]['sequence'] if rows else 0
        fd = os.open(events, os.O_WRONLY | os.O_CREAT | (os.O_APPEND if resume else os.O_EXCL), 0o600)
        self.events = os.fdopen(fd, 'a', encoding='utf-8')

    def add_secret(self, value):
        if isinstance(value, str) and value: self.secrets.add(value)

    def clean(self, value):
        if isinstance(value, str):
            for secret in sorted(self.secrets, key=len, reverse=True): value = value.replace(secret, '[REDACTED]')
            return value
        if isinstance(value, list): return [self.clean(v) for v in value]
        if isinstance(value, dict):
            private = {'authorization', 'api_key', 'deepseek_api_key', 'access_token', 'refresh_token', 'id_token', 'code_verifier', 'client_secret', 'authorization_code'}
            return {k: self.clean(v) for k, v in value.items() if k.lower() not in private}
        return value

    def event(self, kind, **data):
        self.sequence += 1
        self.events.write(json_text(self.clean({'sequence': self.sequence, 'time': time.time(), 'kind': kind, **data})) + '\n')
        self.events.flush(); os.fsync(self.events.fileno())

    def write(self, name, value): atomic_json(self.root / name, self.clean(value))

    def next_api(self):
        self.api_sequence += 1
        return self.api_sequence

    def api_record(self, index, side, value):
        path = self.root / 'api' / f'{index:06}-{side}.json.gz'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as raw:
            with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as out: out.write(json_text(self.clean(value)).encode())
            raw.flush(); os.fsync(raw.fileno())
        return str(path.relative_to(self.root))

    def records(self): return [json.loads(line) for line in (self.root / 'events.jsonl').read_text(encoding='utf-8').splitlines()]

    def close(self):
        if not self.events.closed: self.events.close()
