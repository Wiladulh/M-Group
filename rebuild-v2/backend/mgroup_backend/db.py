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
        lock_fd=self._lock_fd
        self._lock_fd=None
        try:
            return super().close()
        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd,fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)


def connect(database_path: str) -> sqlite3.Connection:
    if database_path == ':memory:':
        connection=sqlite3.connect(database_path,timeout=10,isolation_level=None,check_same_thread=False,factory=LockedConnection)
        connection.row_factory=sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('PRAGMA busy_timeout = 10000')
        return connection
    path=Path(database_path)
    path.parent.mkdir(parents=True,exist_ok=True)
    lock_path=Path(str(path)+'.lock')
    lock_fd=os.open(lock_path,os.O_CREAT|os.O_RDWR,0o600)
    os.fchmod(lock_fd,0o600)
    try:
        fcntl.flock(lock_fd,fcntl.LOCK_SH)
        connection=sqlite3.connect(database_path,timeout=10,isolation_level=None,check_same_thread=False,factory=LockedConnection)
        connection._lock_fd=lock_fd
        connection.row_factory=sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('PRAGMA busy_timeout = 10000')
        return connection
    except Exception:
        try:
            fcntl.flock(lock_fd,fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
        raise


def initialize(database_path: str) -> None:
    connection = connect(database_path)
    try:
        connection.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
        connection.executescript('''
        CREATE TABLE IF NOT EXISTS product_slots (
            registry_id TEXT NOT NULL,
            product_id INTEGER NOT NULL CHECK (product_id BETWEEN 1 AND 5),
            name TEXT NOT NULL,
            price_minor INTEGER NOT NULL CHECK (price_minor >= 0),
            stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
            capacity INTEGER NOT NULL DEFAULT 0 CHECK (capacity >= 0 AND stock <= capacity),
            image_path TEXT,
            nfc_promo_percent INTEGER NOT NULL DEFAULT 0 CHECK (nfc_promo_percent BETWEEN 0 AND 0),
            qris_promo_percent INTEGER NOT NULL DEFAULT 0 CHECK (qris_promo_percent BETWEEN 0 AND 0),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (registry_id, product_id),
            FOREIGN KEY (registry_id) REFERENCES device_registry(registry_id)
        );
        CREATE TABLE IF NOT EXISTS pin_attempts (
            card_hash TEXT NOT NULL,
            hardware_id TEXT NOT NULL,
            failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
            locked_until TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (card_hash, hardware_id)
        );
        CREATE TABLE IF NOT EXISTS pin_card_attempts (
            card_hash TEXT PRIMARY KEY,
            failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
            locked_until TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS cashiers (
            cashier_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS cashier_device_config (
            registry_id TEXT PRIMARY KEY,
            operator_id TEXT NOT NULL,
            operator_name TEXT NOT NULL,
            operator_pin_hash TEXT NOT NULL,
            settlement_account_id TEXT NOT NULL,
            failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
            locked_until TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (registry_id) REFERENCES device_registry(registry_id),
            FOREIGN KEY (settlement_account_id) REFERENCES accounts(account_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_cashier_operator_binding
            ON cashier_device_config(operator_id);
        ''')
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
