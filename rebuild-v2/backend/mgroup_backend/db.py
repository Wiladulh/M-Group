from contextlib import contextmanager
from pathlib import Path
import fcntl
import os
import sqlite3

SCHEMA_PATH = Path(__file__).resolve().parents[2] / 'db' / 'schema.sql'


class LockedConnection(sqlite3.Connection):
    """Connection that holds a shared process lock until closed."""
    _lock_fd = None

    def close(self):
        lock_fd = self._lock_fd
        self._lock_fd = None
        try:
            return super().close()
        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)


def connect(database_path: str) -> sqlite3.Connection:
    if database_path == ':memory:':
        connection = sqlite3.connect(database_path, timeout=10, isolation_level=None,
                                     check_same_thread=False, factory=LockedConnection)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('PRAGMA busy_timeout = 10000')
        return connection
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(path) + '.lock')
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.fchmod(lock_fd, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_SH)
        connection = sqlite3.connect(database_path, timeout=10, isolation_level=None,
                                     check_same_thread=False, factory=LockedConnection)
        connection._lock_fd = lock_fd
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('PRAGMA busy_timeout = 10000')
        return connection
    except Exception:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
        raise


def initialize(database_path: str) -> None:
    """Create the canonical v2 schema without migrating or rewriting existing data.

    v2 is a clean-install application. Schema changes must be delivered as explicit,
    reviewed migrations rather than hidden startup transformations.
    """
    connection = connect(database_path)
    try:
        connection.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
        violations = connection.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            raise sqlite3.IntegrityError(
                f'Foreign key violations after v2 schema initialization: {len(violations)}')
    finally:
        connection.close()


@contextmanager
def transaction(connection: sqlite3.Connection):
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()
