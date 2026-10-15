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



def test_legacy_database_upgrade_preserves_financial_and_vending_records():
    """Exercise a real forward upgrade from the pre-hardening schema with live rows."""
    import shutil

    migrations = Path(__file__).resolve().parents[1] / "app" / "migrations"
    with TemporaryDirectory() as directory:
        root = Path(directory)
        legacy_migrations = root / "legacy-migrations"
        legacy_migrations.mkdir()
        for migration in sorted(migrations.glob("*.sql")):
            if int(migration.name[:3]) <= 10:
                shutil.copy2(migration, legacy_migrations / migration.name)

        db = Database(root / "legacy-m-group.db")
        # Build the legacy schema using only migrations that existed before
        # NFC-payment and vending-promotion table rebuilds.
        db.migrate(migrations_dir=legacy_migrations)
        with db.connect() as c:
            c.execute(
                "INSERT INTO identity_members(member_id,name) VALUES(?,?)",
                ("member-legacy", "Legacy Member"),
            )
            c.execute(
                "INSERT INTO identity_credentials(credential_id,member_id,credential_type,status) "
                "VALUES(?,?,?,?)",
                ("cred-legacy", "member-legacy", "nfc", "active"),
            )
            c.execute(
                "INSERT INTO financial_accounts(account_id,member_id,account_type,status) "
                "VALUES(?,?,?,?)",
                ("acct-legacy", "member-legacy", "savings", "active"),
            )
            c.execute(
                "INSERT INTO financial_ledger(account_id,direction,amount,reference) "
                "VALUES(?,?,?,?)",
                ("acct-legacy", "credit", 5000, "legacy-seed"),
            )
            c.execute(
                "INSERT INTO vending_machines(machine_id,name,status) VALUES(?,?,?)",
                ("machine-legacy", "Legacy machine", "active"),
            )
            c.execute(
                "INSERT INTO vending_products(product_id,machine_id,name,price,stock,enabled) "
                "VALUES(?,?,?,?,?,?)",
                ("product-legacy", "machine-legacy", "Legacy product", 1250, 7, 1),
            )
            c.execute(
                "INSERT INTO payment_transactions(transaction_id,credential_id,account_id,amount,status) "
                "VALUES(?,?,?,?,?)",
                ("payment-legacy", "cred-legacy", "acct-legacy", 1250, "completed"),
            )
            c.execute(
                "INSERT INTO vending_transactions("
                "transaction_id,machine_id,product_id,credential_id,account_id,amount,status) "
                "VALUES(?,?,?,?,?,?,?)",
                ("vending-legacy", "machine-legacy", "product-legacy",
                 "cred-legacy", "acct-legacy", 1250, "completed"),
            )
            c.execute(
                "INSERT INTO device_registry(device_id,device_type,status,last_seen) "
                "VALUES(?,?,?,?)",
                ("device-legacy", "cashier", "active", "2025-01-02 03:04:05"),
            )
            c.commit()

        # Upgrade that populated old database through every current migration.
        db.migrate()

        with db.connect() as c:
            assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert c.execute("PRAGMA foreign_key_check").fetchall() == []

            assert c.execute(
                "SELECT name FROM identity_members WHERE member_id='member-legacy'"
            ).fetchone()[0] == "Legacy Member"
            assert c.execute(
                "SELECT account_id FROM financial_accounts WHERE account_id='acct-legacy'"
            ).fetchone()[0] == "acct-legacy"
            assert c.execute(
                "SELECT direction,amount,reference FROM financial_ledger WHERE account_id='acct-legacy'"
            ).fetchone()[:] == ("credit", 5000, "legacy-seed")

            payment = c.execute(
                "SELECT transaction_id,amount,status,original_amount,final_amount "
                "FROM payment_transactions WHERE transaction_id='payment-legacy'"
            ).fetchone()
            assert payment[:] == ("payment-legacy", 1250, "completed", 1250, 1250)

            vending = c.execute(
                "SELECT transaction_id,amount,status,base_amount,discount_amount,promo_id "
                "FROM vending_transactions WHERE transaction_id='vending-legacy'"
            ).fetchone()
            assert vending[:] == ("vending-legacy", 1250, "completed", 1250, 0, None)

            product = c.execute(
                "SELECT stock,price FROM vending_products WHERE product_id='product-legacy'"
            ).fetchone()
            assert product[:] == (7, 1250)
            device = c.execute(
                "SELECT device_type,status,last_seen,hardware_id FROM device_registry "
                "WHERE device_id='device-legacy'"
            ).fetchone()
            assert device[:] == ("cashier", "active", "2025-01-02 03:04:05", "device-legacy")

        # A second upgrade must be idempotent and must not duplicate or drop rows.
        db.migrate()
        with db.connect() as c:
            assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert c.execute("PRAGMA foreign_key_check").fetchall() == []
            assert c.execute(
                "SELECT COUNT(*) FROM payment_transactions WHERE transaction_id='payment-legacy'"
            ).fetchone()[0] == 1
            assert c.execute(
                "SELECT COUNT(*) FROM vending_transactions WHERE transaction_id='vending-legacy'"
            ).fetchone()[0] == 1
