from contextlib import contextmanager
from pathlib import Path
import fcntl
import os
import re
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
    connection = connect(database_path)
    try:
        # The v2 identity cleanup updates member primary keys and all references
        # together. Foreign-key checks are run again before initialization ends.
        connection.execute('PRAGMA foreign_keys = OFF')
        connection.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))

        migrations = {
            'accounts': {'label': 'TEXT'},
            'members': {
                'nik': 'TEXT',
                'phone': 'TEXT',
                'email': 'TEXT',
                'profile_json': "TEXT NOT NULL DEFAULT '{}'",
            },
            'product_slots': {
                'capacity': 'INTEGER NOT NULL DEFAULT 0',
                'enabled': 'INTEGER NOT NULL DEFAULT 0',
            },
            'nfc_registration_sessions': {
                'replace_existing': 'INTEGER NOT NULL DEFAULT 0',
            },
        }
        for table, columns in migrations.items():
            existing = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        connection.execute('UPDATE product_slots SET capacity=stock WHERE capacity<stock')

        connection.execute('BEGIN IMMEDIATE')
        try:
            config_columns = {row[1] for row in connection.execute('PRAGMA table_info(cashier_device_config)')}
            if 'settlement_account_id' in config_columns and len(config_columns) > 3:
                connection.execute('ALTER TABLE cashier_device_config RENAME TO cashier_device_config_old')
                connection.execute('''CREATE TABLE cashier_device_config (
                    registry_id TEXT PRIMARY KEY,
                    settlement_account_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (registry_id) REFERENCES device_registry(registry_id),
                    FOREIGN KEY (settlement_account_id) REFERENCES accounts(account_id)
                )''')
                connection.execute('''INSERT INTO cashier_device_config(registry_id,settlement_account_id,updated_at)
                    SELECT registry_id,settlement_account_id,updated_at FROM cashier_device_config_old''')
                connection.execute('DROP TABLE cashier_device_config_old')
            connection.execute('DROP TABLE IF EXISTS cashiers')

            # Keep exactly one active Admin super-admin account.
            admin_columns = {row[1] for row in connection.execute('PRAGMA table_info(admin_users)')}
            admins = connection.execute(
                "SELECT admin_id FROM admin_users WHERE status='active' ORDER BY created_at,admin_id"
            ).fetchall()
            if not admins:
                admins = connection.execute(
                    "SELECT admin_id FROM admin_users ORDER BY created_at,admin_id"
                ).fetchall()
            if admins:
                keep = admins[0]['admin_id']
                connection.execute("DELETE FROM admin_sessions WHERE admin_id<>?", (keep,))
                connection.execute("DELETE FROM admin_users WHERE admin_id<>?", (keep,))
                if 'role' in admin_columns:
                    connection.execute(
                        "UPDATE admin_users SET role='super_admin',status='active',updated_at=CURRENT_TIMESTAMP WHERE admin_id=?",
                        (keep,))

            # Rename old member identifiers to sequential UID identifiers and
            # preserve all relational, audit, and JSON references.
            members = connection.execute(
                'SELECT member_id FROM members ORDER BY created_at,member_id'
            ).fetchall()
            existing = {
                row['member_id'] for row in members
                if re.fullmatch(r'UID-[0-9]+', row['member_id'] or '')
            }
            next_number = max((int(value[4:]) for value in existing), default=0)
            mapping = {}
            for row in members:
                old = row['member_id']
                if not re.fullmatch(r'UID-[0-9]+', old or ''):
                    next_number += 1
                    mapping[old] = f'UID-{next_number:05d}'

            for old, new in mapping.items():
                for table in ('member_cards', 'accounts', 'transactions', 'nfc_registration_sessions'):
                    connection.execute(f'UPDATE {table} SET member_id=? WHERE member_id=?', (new, old))
                connection.execute(
                    "UPDATE audit_events SET entity_id=? WHERE entity_type='member' AND entity_id=?",
                    (new, old))
                connection.execute(
                    'UPDATE transactions SET metadata_json=replace(metadata_json,?,?)', (old, new))
                connection.execute(
                    'UPDATE audit_events SET detail_json=replace(detail_json,?,?)', (old, new))
                connection.execute('UPDATE members SET member_id=? WHERE member_id=?', (new, old))

            connection.commit()
        except Exception:
            connection.rollback()
            raise

        connection.execute('PRAGMA foreign_keys = ON')
        violations = connection.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            raise sqlite3.IntegrityError(
                f'Foreign key violations after v2 identity cleanup: {len(violations)}')
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
