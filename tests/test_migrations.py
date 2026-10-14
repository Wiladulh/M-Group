from pathlib import Path
import os
import stat
from tempfile import TemporaryDirectory

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
