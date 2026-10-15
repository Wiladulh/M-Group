from pathlib import Path
import os
import stat
import hashlib
import secrets
from tempfile import TemporaryDirectory
from threading import Event, Thread

from app.core.db import Database


def test_canonical_migrations_are_repeatable_and_integrity_clean():
    with TemporaryDirectory() as directory:
        db = Database(Path(directory) / "m-group.db")
        db.migrate()
        db.migrate()
        if os.name == "posix":
            assert stat.S_IMODE(db.path.stat().st_mode) == 0o600
        with db.connect() as c:
            assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert c.execute("PRAGMA foreign_key_check").fetchall() == []
            operator_pin = c.execute(
                "SELECT value FROM system_meta WHERE key='cashier_operator_pin_hash'"
            ).fetchone()
            assert operator_pin is None or not operator_pin["value"]
            tables = {
                row[0]
                for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            assert {
                "identity_members",
                "financial_accounts",
                "financial_ledger",
                "vending_machines",
                "vending_products",
                "vending_transactions",
                "device_registry",
                "audit_events",
            } <= tables
            triggers = {
                row[0]
                for row in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
            }
            assert "trg_vending_transaction_integrity_update" in triggers


def test_upgrade_removes_only_the_known_legacy_default_operator_pin():
    with TemporaryDirectory() as directory:
        db = Database(Path(directory) / "m-group.db")
        db.migrate()
        salt = secrets.token_hex(16)
        default_hash = hashlib.pbkdf2_hmac("sha256", b"9992", salt.encode(), 120000).hex()
        with db.connect() as c:
            c.execute(
                "INSERT OR REPLACE INTO system_meta(key,value) VALUES('cashier_operator_pin_hash',?)",
                (salt + ":" + default_hash,),
            )
            c.execute("DELETE FROM system_meta WHERE key='cashier_operator_pin_security_version'")
            c.commit()
        db.migrate()
        with db.connect() as c:
            assert c.execute(
                "SELECT value FROM system_meta WHERE key='cashier_operator_pin_hash'"
            ).fetchone() is None

        # A custom operator PIN hash must survive the same one-time migration.
        salt = secrets.token_hex(16)
        custom_hash = hashlib.pbkdf2_hmac("sha256", b"4321", salt.encode(), 120000).hex()
        with db.connect() as c:
            c.execute(
                "INSERT OR REPLACE INTO system_meta(key,value) VALUES('cashier_operator_pin_hash',?)",
                (salt + ":" + custom_hash,),
            )
            c.execute("DELETE FROM system_meta WHERE key='cashier_operator_pin_security_version'")
            c.commit()
        db.migrate()
        with db.connect() as c:
            stored = c.execute(
                "SELECT value FROM system_meta WHERE key='cashier_operator_pin_hash'"
            ).fetchone()[0]
            stored_salt, stored_hash = stored.split(":", 1)
            expected = hashlib.pbkdf2_hmac("sha256", b"4321", stored_salt.encode(), 120000).hex()
            assert secrets.compare_digest(stored_hash, expected)


def test_installer_supplied_operator_pin_is_hashed_on_initialization(monkeypatch):
    with TemporaryDirectory() as directory:
        monkeypatch.setenv("M_GROUP_CASHIER_OPERATOR_PIN", "2468")
        db = Database(Path(directory) / "m-group.db")
        db.migrate()
        with db.connect() as c:
            stored = c.execute(
                "SELECT value FROM system_meta WHERE key='cashier_operator_pin_hash'"
            ).fetchone()[0]
        salt, digest = stored.split(":", 1)
        expected = hashlib.pbkdf2_hmac("sha256", b"2468", salt.encode(), 120000).hex()
        assert secrets.compare_digest(digest, expected)



def test_context_managed_database_connection_is_closed():
    with TemporaryDirectory() as directory:
        db = Database(Path(directory) / "m-group.db")
        with db.connect() as connection:
            connection.execute("CREATE TABLE connection_lifecycle_test (value INTEGER)")
        try:
            connection.execute("SELECT 1")
        except Exception as exc:
            assert "closed" in str(exc).lower()
        else:
            raise AssertionError("Database context manager left the SQLite connection open")


def test_exclusive_database_lock_waits_for_open_connections():
    with TemporaryDirectory() as directory:
        db = Database(Path(directory) / "m-group.db")
        db.migrate()
        acquired = Event()
        worker_errors = []

        def take_exclusive_lock():
            try:
                with db.exclusive_lock():
                    acquired.set()
            except Exception as exc:
                worker_errors.append(exc)

        with db.connect():
            worker = Thread(target=take_exclusive_lock, daemon=True)
            worker.start()
            assert not acquired.wait(0.15), "exclusive lock bypassed an open database connection"

        assert acquired.wait(3), "exclusive lock did not proceed after the connection closed"
        worker.join(timeout=3)
        assert not worker.is_alive(), "exclusive lock worker did not finish"
        assert not worker_errors, worker_errors
