from contextlib import contextmanager
from pathlib import Path
import sqlite3

SCHEMA_PATH = Path(__file__).resolve().parents[2] / 'db' / 'schema.sql'


def connect(database_path: str) -> sqlite3.Connection:
    if database_path != ':memory:':
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    connection.execute('PRAGMA busy_timeout = 10000')
    return connection


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
        CREATE TABLE IF NOT EXISTS cashiers (
            cashier_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
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
