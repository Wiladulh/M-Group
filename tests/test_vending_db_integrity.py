from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3

from app.core.db import Database


def _seed_vending(db: Database) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO vending_machines(machine_id, name, status) VALUES(?, ?, ?)",
            ("machine-a", "Machine A", "active"),
        )
        conn.execute(
            """INSERT INTO vending_products
               (product_id, machine_id, name, price, stock)
               VALUES(?, ?, ?, ?, ?)""",
            ("water-a", "machine-a", "Water", 5000, 3),
        )


def test_vending_integrity_triggers_reject_invalid_writes_and_allow_zero_promo():
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "integrity.db")
        db.migrate()
        _seed_vending(db)

        with db.connect() as conn:
            # A zero final amount is valid for a 100% promotion.
            conn.execute(
                """INSERT INTO vending_transactions
                   (transaction_id, machine_id, product_id, amount, status,
                    credential_id, account_id, idempotency_key)
                   VALUES('promo-tx', 'machine-a', 'water-a', 0, 'completed',
                          'credential-a', 'account-a', 'promo-once')"""
            )

            invalid_writes = [
                ("""INSERT INTO vending_products
                     (product_id, machine_id, name, price, stock)
                     VALUES('bad-price', 'machine-a', 'Bad', 0, 1)""",
                 "vending_product_price_must_be_positive"),
                ("""INSERT INTO vending_products
                     (product_id, machine_id, name, price, stock)
                     VALUES('bad-machine', 'missing-machine', 'Bad', 100, 1)""",
                 "vending_machine_not_found"),
                ("""INSERT INTO vending_products
                     (product_id, machine_id, name, price, stock)
                     VALUES('bad-stock', 'machine-a', 'Bad', 100, -1)""",
                 "vending_product_stock_must_be_nonnegative"),
                ("""INSERT INTO vending_transactions
                     (transaction_id, machine_id, product_id, amount, status,
                      credential_id, account_id)
                     VALUES('bad-tx-machine', 'missing-machine', 'water-a', 10,
                            'pending', 'credential-a', 'account-a')""",
                 "vending_machine_not_found"),
                ("""INSERT INTO vending_transactions
                     (transaction_id, machine_id, product_id, amount, status,
                      credential_id, account_id)
                     VALUES('bad-tx-product', 'machine-a', 'missing-product', 10,
                            'pending', 'credential-a', 'account-a')""",
                 "vending_product_not_found"),
                ("""INSERT INTO vending_transactions
                     (transaction_id, machine_id, product_id, amount, status,
                      credential_id, account_id)
                     VALUES('bad-tx-amount', 'machine-a', 'water-a', -1,
                            'pending', 'credential-a', 'account-a')""",
                 "vending_transaction_amount_must_be_nonnegative"),
                ("""INSERT INTO vending_transactions
                     (transaction_id, machine_id, product_id, amount, status,
                      credential_id, account_id, idempotency_key)
                     VALUES('duplicate-key', 'machine-a', 'water-a', 100,
                            'pending', 'credential-a', 'account-a', 'promo-once')""",
                 "vending_idempotency_key_conflict"),
            ]

            for sql, expected in invalid_writes:
                try:
                    conn.execute(sql)
                except sqlite3.IntegrityError as exc:
                    assert expected in str(exc)
                else:
                    raise AssertionError(f"Expected integrity rejection: {expected}")


def test_vending_integrity_migration_is_idempotent_and_preserves_existing_rows():
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "legacy.db")
        db.migrate()
        _seed_vending(db)
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO vending_transactions
                   (transaction_id, machine_id, product_id, amount, status,
                    credential_id, account_id)
                   VALUES('legacy-tx', 'machine-a', 'water-a', 250, 'completed',
                          'credential-a', 'account-a')"""
            )

        # Re-running migrations must not duplicate or destroy data.
        db.migrate()
        with db.connect() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM vending_transactions WHERE transaction_id='legacy-tx'"
            ).fetchone()[0] == 1
            trigger_names = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' "
                    "AND name LIKE 'trg_vending_%'"
                )
            }
            assert {
                "trg_vending_product_integrity_insert",
                "trg_vending_product_integrity_update",
                "trg_vending_transaction_integrity_insert",
                "trg_vending_transaction_integrity_update",
            } <= trigger_names
