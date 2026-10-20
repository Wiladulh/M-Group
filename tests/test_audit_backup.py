from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
import hashlib
import app.main as main

from tests.auth_helpers import login_admin
def test_cashier_deposit_and_audit_are_separate_from_vending():
    with TemporaryDirectory() as d:
        old=main.get_settings
        main.get_settings=lambda: type("S",(),{
            "db_path":Path(d)/"m-group.db","data_dir":Path(d),})()
        try:
            client=TestClient(main.create_app())
            assert client.post("/api/v1/cashier/operator-pin",json={"pin":"9992"},headers=login_admin(client)).status_code==200
            with client.app.state.db.connect() as c:
                c.execute("INSERT INTO identity_members(member_id,name) VALUES('m1','Member')")
                c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('a1','m1','savings')")
                c.execute("INSERT INTO identity_credentials(credential_id,member_id,credential_type,status,enabled) VALUES('cred1','m1','nfc','active',1)")
                c.execute("INSERT INTO device_registry(device_id,device_type,status,auth_key_hash) VALUES('cash-01','esp32-cashier','active',?)",(hashlib.sha256(b'cash-key').hexdigest(),))
                c.execute("INSERT INTO vending_machines(machine_id,name,status,device_id) VALUES('v1','V1','active','vend-01')")
                c.execute("INSERT INTO vending_products(product_id,machine_id,name,price,stock) VALUES('p1','v1','P1',5000,1)")
                c.execute("INSERT INTO device_registry(device_id,device_type,status,auth_key_hash) VALUES('vend-01','esp32-s3-vending','active',?)",(hashlib.sha256(b'vend-key').hexdigest(),))
                c.commit()
            assert client.post("/api/v1/members/m1/pin",json={"pin":"1234","operator_id":"test-admin","identity_verified":True,"reason":"test identity verified"},headers=login_admin(client)).status_code==200
            dep=client.post("/api/v1/cashier/deposits",
                json={"credential_id":"cred1","amount":10500,"operator_pin":"9992","member_pin":"1234","idempotency_key":"dep-1"},
                headers={"X-M-Group-Device-Key":"cash-key","X-M-Group-Device-Id":"cash-01"})
            assert dep.status_code==200
            assert dep.json()["balance_after"]==10500
            report=client.get("/api/v1/audit/report?source=CASHIER&period=day",headers=login_admin(client))
            assert report.status_code==200
            assert all(x["source"]=="CASHIER" for x in report.json()["transactions"])
            assert report.json()["transactions"][0]["amount"]==10500
        finally:
            main.get_settings=old

def test_operator_pin_can_be_changed_by_admin():
    with TemporaryDirectory() as d:
        old=main.get_settings
        main.get_settings=lambda: type("S",(),{
            "db_path":Path(d)/"m-group.db","data_dir":Path(d),})()
        try:
            client=TestClient(main.create_app())
            r=client.post("/api/v1/cashier/operator-pin",json={"pin":"4321"},headers=login_admin(client))
            assert r.status_code==200
            with client.app.state.db.connect() as c:
                c.execute("INSERT INTO identity_members(member_id,name) VALUES('m1','Member')")
                c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('a1','m1','savings')")
                c.execute("INSERT INTO identity_credentials(credential_id,member_id,credential_type,status,enabled) VALUES('cred1','m1','nfc','active',1)")
                c.execute("INSERT INTO device_registry(device_id,device_type,status,auth_key_hash) VALUES('cash-01','esp32-cashier','active',?)",(hashlib.sha256(b'cash-key').hexdigest(),))
                c.commit()
            assert client.post("/api/v1/members/m1/pin",json={"pin":"1234","operator_id":"test-admin","identity_verified":True,"reason":"test identity verified"},headers=login_admin(client)).status_code==200
            ok=client.post("/api/v1/cashier/deposits",json={"credential_id":"cred1","amount":1000,"operator_pin":"4321","member_pin":"1234","idempotency_key":"dep-2"},headers={"X-M-Group-Device-Key":"cash-key","X-M-Group-Device-Id":"cash-01"})
            assert ok.status_code==200
            bad=client.post("/api/v1/cashier/deposits",json={"credential_id":"cred1","amount":1000,"operator_pin":"9992","member_pin":"1234","idempotency_key":"dep-3"},headers={"X-M-Group-Device-Key":"cash-key","X-M-Group-Device-Id":"cash-01"})
            assert bad.status_code==403
        finally:
            main.get_settings=old


def test_native_restore_replaces_database_atomically():
    from app.core.backup import create_native_backup, restore_native_backup
    with TemporaryDirectory() as d:
        old=main.get_settings
        root=Path(d)
        main.get_settings=lambda: type("S",(),{
            "db_path":root/"m-group.db","data_dir":root,})()
        try:
            app=main.create_app()
            with app.state.db.connect() as db:
                db.execute("INSERT INTO identity_members(member_id,name) VALUES('restore-member','Before')")
                db.commit()
            archive=root/"backup.m_group.zip"
            create_native_backup(app.state.db,archive,include_excel=False)
            with app.state.db.connect() as db:
                db.execute("INSERT INTO identity_members(member_id,name) VALUES('live-only','Should disappear')")
                db.commit()
            restore_native_backup(app.state.db,archive)
            with app.state.db.connect() as db:
                assert db.execute("SELECT 1 FROM identity_members WHERE member_id='restore-member'").fetchone()
                assert db.execute("SELECT 1 FROM identity_members WHERE member_id='live-only'").fetchone() is None
        finally:
            main.get_settings=old


def test_native_restore_checkpoints_wal_before_swapping_database():
    from app.core.backup import create_native_backup, restore_native_backup

    with TemporaryDirectory() as directory:
        root = Path(directory)
        old = main.get_settings
        main.get_settings = lambda: type(
            "Settings", (), {
                "db_path": root / "m-group.db",
                "data_dir": root,
            }
        )()
        try:
            app = main.create_app()
            db = app.state.db
            with db.connect() as connection:
                assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
                connection.execute(
                    "INSERT INTO identity_members(member_id,name) VALUES(?,?)",
                    ("restore-wal-member", "Restored member"),
                )
                connection.commit()

            archive = root / "wal-backup.mgroup.zip"
            create_native_backup(db, archive, include_excel=False)

            with db.connect() as connection:
                connection.execute(
                    "INSERT INTO identity_members(member_id,name) VALUES(?,?)",
                    ("live-wal-only", "Must not survive restore"),
                )
                connection.commit()

            restore_native_backup(db, archive)

            with db.connect() as connection:
                assert connection.execute(
                    "SELECT 1 FROM identity_members WHERE member_id='restore-wal-member'"
                ).fetchone()
                assert connection.execute(
                    "SELECT 1 FROM identity_members WHERE member_id='live-wal-only'"
                ).fetchone() is None
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

            assert not Path(str(db.path) + "-wal").exists()
            assert not Path(str(db.path) + "-shm").exists()
        finally:
            main.get_settings = old


def test_native_restore_failure_preserves_live_database():
    from app.core.backup import create_native_backup, restore_native_backup
    from zipfile import ZipFile
    import json
    import sqlite3

    with TemporaryDirectory() as directory:
        root = Path(directory)
        old = main.get_settings
        main.get_settings = lambda: type(
            "Settings", (), {
                "db_path": root / "m-group.db",
                "data_dir": root,
            }
        )()
        try:
            app = main.create_app()
            db = app.state.db
            with db.connect() as connection:
                connection.execute(
                    "INSERT INTO identity_members(member_id, name) VALUES(?, ?)",
                    ("must-survive", "Live database"),
                )
                connection.commit()

            archive = root / "broken-restore.mgroup.zip"
            create_native_backup(db, archive, include_excel=False)

            # Make the archive checksum valid but the SQL payload invalid. This
            # exercises failure after archive validation and before live swap.
            with ZipFile(archive, "r") as source:
                entries = {item.filename: source.read(item.filename) for item in source.infolist()}
            entries["database.sql"] = b"THIS IS NOT VALID SQLITE SQL;"
            entries["checksum.sha256"] = (
                hashlib.sha256(entries["database.sql"]).hexdigest() + "  database.sql\n"
            ).encode("ascii")
            with ZipFile(archive, "w") as target:
                for name, payload in entries.items():
                    target.writestr(name, payload)

            try:
                restore_native_backup(db, archive)
            except sqlite3.Error:
                pass
            else:
                raise AssertionError("invalid restore SQL unexpectedly succeeded")

            with db.connect() as connection:
                row = connection.execute(
                    "SELECT name FROM identity_members WHERE member_id=?",
                    ("must-survive",),
                ).fetchone()
                assert row is not None and row["name"] == "Live database"
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            main.get_settings = old




def test_native_restore_waits_for_inflight_database_users():
    from app.core.backup import create_native_backup, restore_native_backup
    from threading import Event, Thread

    with TemporaryDirectory() as directory:
        root = Path(directory)
        old = main.get_settings
        main.get_settings = lambda: type(
            "Settings", (), {
                "db_path": root / "m-group.db",
                "data_dir": root,
            }
        )()
        try:
            db = main.create_app().state.db
            with db.connect() as connection:
                connection.execute(
                    "INSERT INTO identity_members(member_id, name) VALUES(?, ?)",
                    ("from-backup", "Backup member"),
                )
                connection.commit()

            archive = root / "concurrent-restore.mgroup.zip"
            create_native_backup(db, archive, include_excel=False)

            with db.connect() as connection:
                connection.execute(
                    "INSERT INTO identity_members(member_id, name) VALUES(?, ?)",
                    ("live-only", "Current live member"),
                )
                connection.commit()

            connection_open = Event()
            release_connection = Event()
            restore_finished = Event()
            restore_errors = []

            def hold_database_connection():
                with db.connect():
                    connection_open.set()
                    if not release_connection.wait(5):
                        raise AssertionError("test did not release active database connection")

            def restore_in_background():
                try:
                    restore_native_backup(db, archive)
                except Exception as exc:
                    restore_errors.append(exc)
                finally:
                    restore_finished.set()

            holder = Thread(target=hold_database_connection, daemon=True)
            holder.start()
            assert connection_open.wait(3), "database holder did not start"

            restorer = Thread(target=restore_in_background, daemon=True)
            restorer.start()
            assert not restore_finished.wait(0.2), (
                "restore swapped the live database while a managed connection was active"
            )

            release_connection.set()
            holder.join(timeout=3)
            restorer.join(timeout=5)
            assert not holder.is_alive(), "database holder thread did not finish"
            assert not restorer.is_alive(), "restore thread did not finish"
            assert not restore_errors, restore_errors

            with db.connect() as connection:
                assert connection.execute(
                    "SELECT 1 FROM identity_members WHERE member_id='from-backup'"
                ).fetchone()
                assert connection.execute(
                    "SELECT 1 FROM identity_members WHERE member_id='live-only'"
                ).fetchone() is None
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            main.get_settings = old

def test_native_backup_restore_preserves_financial_ledger_and_balance():
    from app.core.backup import create_native_backup, restore_native_backup
    from app.financial.service import FinancialService

    with TemporaryDirectory() as directory:
        root = Path(directory)
        old = main.get_settings
        main.get_settings = lambda: type(
            "Settings", (), {
                "db_path": root / "m-group.db",
                "data_dir": root,
            }
        )()
        try:
            app = main.create_app()
            db = app.state.db
            with db.connect() as c:
                c.execute("INSERT INTO identity_members(member_id,name) VALUES('restore-fin-member','Member')")
                c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('restore-fin-account','restore-fin-member','savings')")
                c.commit()

            financial = FinancialService(db)
            financial.credit("restore-fin-account", 50000, reference="pre-backup", idempotency_key="restore-pre-backup")
            before = financial.balance("restore-fin-account")
            archive = root / "financial-backup.mgroup.zip"
            create_native_backup(db, archive, include_excel=False)
            financial.debit("restore-fin-account", 10000, reference="post-backup", idempotency_key="restore-post-backup")

            restore_native_backup(db, archive)
            restored = FinancialService(db)
            assert restored.balance("restore-fin-account") == before
            with db.connect() as c:
                assert c.execute("SELECT COUNT(*) FROM financial_ledger WHERE account_id='restore-fin-account'").fetchone()[0] == 1
                assert c.execute("SELECT COUNT(*) FROM financial_transactions WHERE idempotency_key='restore-pre-backup'").fetchone()[0] == 1
                assert c.execute("SELECT COUNT(*) FROM financial_transactions WHERE idempotency_key='restore-post-backup'").fetchone()[0] == 0
                assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            main.get_settings = old
