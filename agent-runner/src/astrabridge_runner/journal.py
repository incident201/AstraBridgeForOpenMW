import base64
import gzip
import hashlib
import json
import os
import time
import uuid
from pathlib import Path


def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(json_text(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Journal:
    def __init__(self, parent, secret='', *, resume=None):
        self.root = Path(resume).resolve() if resume else Path(parent).resolve() / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
        self.root.mkdir(parents=True, mode=0o700, exist_ok=bool(resume))
        self.secrets = set()
        self.add_secret(secret)
        for name in ('api', 'images'):
            (self.root / name).mkdir(mode=0o700, exist_ok=bool(resume))
        self.sequence = 0
        self.api_sequence = max([int(p.name.split('-')[0]) for p in (self.root / 'api').glob('*.json.gz')] or [0])
        events = self.root / 'events.jsonl'
        if resume:
            data = events.read_bytes()
            if data and not data.endswith(b'\n'):
                split = data.rfind(b'\n') + 1
                fragment = self.root / ('events-incomplete-' + uuid.uuid4().hex + '.log')
                fd = os.open(fragment, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data[split:])
                data = data[:split]
                with events.open('wb') as stream:
                    stream.write(data)
            rows = [json.loads(line) for line in data.splitlines()]
            self.sequence = rows[-1]['sequence'] if rows else 0
        fd = os.open(events, os.O_WRONLY | os.O_CREAT | (os.O_APPEND if resume else os.O_EXCL), 0o600)
        self.events = os.fdopen(fd, 'a', encoding='utf-8')

    def add_secret(self, value):
        if isinstance(value, str) and value:
            self.secrets.add(value)

    def clean(self, value):
        if isinstance(value, str):
            for secret in sorted(self.secrets, key=len, reverse=True):
                value = value.replace(secret, '[REDACTED]')
            return value
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        if isinstance(value, dict):
            private = {'authorization', 'api_key', 'deepseek_api_key', 'access_token', 'refresh_token', 'id_token', 'code_verifier', 'client_secret', 'authorization_code'}
            return {k: self.clean(v) for k, v in value.items() if k.lower() not in private}
        return value

    def event(self, kind, **data):
        self.sequence += 1
        self.events.write(json_text(self.clean({'sequence': self.sequence, 'time': time.time(), 'kind': kind, **data})) + '\n')
        self.events.flush()
        os.fsync(self.events.fileno())

    def write(self, name, value):
        atomic_json(self.root / name, self.clean(value))

    def next_api(self):
        self.api_sequence += 1
        return self.api_sequence

    def api_record(self, index, side, value):
        path = self.root / 'api' / f'{index:06}-{side}.json.gz'
        value = self.clean(value)
        if side == 'request':
            value = self.archive_request_images(value)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as raw:
            with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as out:
                out.write(json_text(value).encode())
            raw.flush()
            os.fsync(raw.fileno())
        return str(path.relative_to(self.root))

    def archive_request_images(self, value):
        """Store each image once, retaining an exactly reconstructable request."""
        references = {}
        extensions = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/gif': '.gif', 'image/webp': '.webp'}

        def visit(item, location):
            if isinstance(item, str) and item.startswith('data:image/'):
                header, separator, encoded = item.partition(',')
                mime = header.removeprefix('data:').removesuffix(';base64')
                if not separator or not header.endswith(';base64') or mime not in extensions:
                    return item
                try:
                    data = base64.b64decode(encoded, validate=True)
                except ValueError:
                    return item
                # Noncanonical external URLs are logged verbatim so no detail
                # of the original request is normalized or silently lost.
                if base64.b64encode(data).decode('ascii') != encoded:
                    return item
                digest = hashlib.sha256(data).hexdigest()
                relative = 'images/' + digest + extensions[mime]
                destination = self.root / relative
                if not destination.exists():
                    temporary = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.tmp')
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    try:
                        with os.fdopen(fd, 'wb') as image:
                            image.write(data)
                            image.flush()
                            os.fsync(image.fileno())
                        os.replace(temporary, destination)
                    finally:
                        temporary.unlink(missing_ok=True)
                reference = 'astrabridge-archive://' + relative
                info = references.setdefault(reference, {
                    'path': relative, 'mime': mime, 'sha256': digest, 'locations': [],
                })
                info['locations'].append(location)
                return reference
            if isinstance(item, list):
                return [visit(child, [*location, index]) for index, child in enumerate(item)]
            if isinstance(item, dict):
                return {key: visit(child, [*location, key]) for key, child in item.items()}
            return item

        result = visit(value, [])
        if references:
            result = {**result, 'image_archive': {'schema': 1, 'references': references}}
        return result

    def read_api_record(self, name):
        return read_api_record(self.root, name)

    def records(self):
        return [json.loads(line) for line in (self.root / 'events.jsonl').read_text(encoding='utf-8').splitlines()]

    def close(self):
        if not self.events.closed:
            self.events.close()


def read_api_record(root, name):
    """Restore old/new API records without opening or changing the journal."""
    root = Path(root).resolve()
    path = (root / name).resolve()
    api_root = (root / 'api').resolve()
    if not api_root.is_relative_to(root) or not path.is_relative_to(api_root):
        raise ValueError('API record is outside this session archive.')
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        value = json.load(stream)
    archive = value.pop('image_archive', None)
    if archive is None:
        return value
    if archive.get('schema') != 1:
        raise ValueError('Unsupported API image archive format.')
    for reference, info in archive['references'].items():
        image = (root / info['path']).resolve()
        image_root = (root / 'images').resolve()
        if not image_root.is_relative_to(root) or not image.is_relative_to(image_root):
            raise ValueError('Archived API image is outside this session archive.')
        data = image.read_bytes()
        if hashlib.sha256(data).hexdigest() != info['sha256']:
            raise ValueError('Archived API image was modified.')
        restored = 'data:' + info['mime'] + ';base64,' + base64.b64encode(data).decode('ascii')
        for location in info['locations']:
            if not location:
                raise ValueError('Invalid archived API image location.')
            target = value
            for key in location[:-1]:
                target = target[key]
            if target[location[-1]] != reference:
                raise ValueError('Archived API image reference was modified.')
            target[location[-1]] = restored
    return value
