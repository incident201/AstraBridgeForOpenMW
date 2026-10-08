import os
from pathlib import Path


class FileLock:
    """Separate lock files survive atomic replacement of the protected data."""
    def __init__(self, path, blocking=True): self.path, self.blocking, self.file = Path(path), blocking, None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = os.fdopen(os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600), 'r+b')
        try:
            if os.name == 'nt':
                import msvcrt
                if self.path.stat().st_size == 0: self.file.write(b'0'); self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_LOCK if self.blocking else msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | (0 if self.blocking else fcntl.LOCK_NB))
        except OSError as exc:
            self.file.close(); self.file = None
            raise RuntimeError('This session is already active in another process.') from exc
        return self

    def __exit__(self, *_):
        if self.file:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0); msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_UN)
            self.file.close(); self.file = None
