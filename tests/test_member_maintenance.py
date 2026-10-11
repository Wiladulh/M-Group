from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.db import Database
from app.financial.service import FinancialService


def test_topup_correction_is_ledger_backed_and_idempotent():
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "nvm.db")
        db.migrate()
        with db.connect() as c:
            c.execute("INSERT INTO identity_members(member_id,name) VALUES('NTR-00001','Test Member')")
            c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('NTR-00001','NTR-00001','savings')")
            c.commit()
        financial = FinancialService(db)
        original = financial.credit("NTR-00001", 10000, reference="topup", idempotency_key="topup-test-1")
        corrected = financial.correct_credit(
            "NTR-00001", original["transaction_id"], 7000,
            "Input nominal salah", "correct-test-0001", "operator-test"
        )
        assert corrected["original_amount"] == 10000
        assert corrected["corrected_amount"] == 7000
        assert corrected["adjustment_amount"] == -3000
        assert financial.balance("NTR-00001") == 7000
        replay = financial.correct_credit(
            "NTR-00001", original["transaction_id"], 7000,
            "Input nominal salah", "correct-test-0001", "operator-test"
        )
        assert replay["correction_id"] == corrected["correction_id"]
        assert replay["replayed"] is True
        with db.connect() as c:
            assert c.execute("SELECT COUNT(*) FROM financial_corrections").fetchone()[0] == 1
            assert c.execute("SELECT COUNT(*) FROM financial_ledger WHERE account_id='NTR-00001'").fetchone()[0] == 2


def test_topup_correction_rejects_duplicate_and_invalid_amount():
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "nvm.db")
        db.migrate()
        with db.connect() as c:
            c.execute("INSERT INTO identity_members(member_id,name) VALUES('NTR-00002','Test Member')")
            c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('NTR-00002','NTR-00002','savings')")
            c.commit()
        financial = FinancialService(db)
        original = financial.credit("NTR-00002", 5000, idempotency_key="topup-test-2")
        financial.correct_credit("NTR-00002", original["transaction_id"], 4000, "Koreksi valid", "correct-test-0002", "operator-test")
        try:
            financial.correct_credit("NTR-00002", original["transaction_id"], 3000, "Koreksi ulang", "correct-test-0003", "operator-test")
            assert False, "second correction must be rejected"
        except ValueError as exc:
            assert str(exc) == "original_transaction_already_corrected"
        try:
            financial.correct_credit("NTR-00002", "missing", 0, "Invalid", "correct-test-0004", "operator-test")
            assert False, "invalid amount must be rejected"
        except ValueError as exc:
            assert str(exc) == "corrected_amount_must_be_positive_integer"


def test_pin_reset_requires_admin_and_identity_verification():
    from fastapi.testclient import TestClient
    import app.main as main

    with TemporaryDirectory() as tmp:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {"db_path": Path(tmp) / "nvm.db", "admin_token": "admin-secret"})()
        try:
            client = TestClient(main.create_app())
            with client.app.state.db.connect() as c:
                c.execute("INSERT INTO identity_members(member_id,name) VALUES('NTR-00003','PIN Test')")
                c.commit()
            url = "/api/v1/members/NTR-00003/pin"
            assert client.post(url, json={"pin": "1234"}).status_code == 401
            admin = {"X-NVM-Admin-Token": "admin-secret"}
            assert client.post(url, headers=admin, json={"pin": "1234", "operator_id": "operator-1"}).status_code == 400
            response = client.post(url, headers=admin, json={
                "pin": "1234", "operator_id": "operator-1",
                "reason": "Member verified in person", "identity_verified": True
            })
            assert response.status_code == 200
            with client.app.state.db.connect() as c:
                row = c.execute("SELECT pin_salt,pin_hash FROM identity_members WHERE member_id='NTR-00003'").fetchone()
                assert row["pin_hash"] != "1234"
                assert c.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='member_pin_reset'").fetchone()[0] == 1
        finally:
            main.get_settings = old


def test_nfc_replacement_revokes_old_credential():
    import hashlib
    from fastapi.testclient import TestClient
    import app.main as main

    with TemporaryDirectory() as tmp:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {"db_path": Path(tmp) / "nvm.db", "admin_token": "admin-secret"})()
        try:
            client = TestClient(main.create_app())
            admin = {"X-NVM-Admin-Token": "admin-secret"}
            with client.app.state.db.connect() as c:
                c.execute("INSERT INTO identity_members(member_id,name) VALUES('NTR-00004','NFC Test')")
                c.execute("INSERT INTO device_registry(device_id,device_type,status,auth_key_hash) VALUES(?,?,?,?)",
                          ("cashier-test", "esp32-cashier", "active", hashlib.sha256(b"cash-key").hexdigest()))
                c.commit()

            start = client.post("/api/v1/members/NTR-00004/nfc-registration/start", headers=admin,
                                json={"cashier_device_id": "cashier-test"})
            assert start.status_code == 200
            first = client.post("/api/v1/cashier/cashier-test/nfc-registration/complete",
                                headers={"X-NVM-Device-Key": "cash-key"},
                                json={"session_id": start.json()["session_id"], "card_uid": "04:AA:BB:CC:01", "pin": "1234"})
            assert first.status_code == 200
            old_credential = first.json()["credential_id"]

            replacement = client.post("/api/v1/members/NTR-00004/nfc-replacement/start", headers=admin,
                                      json={"cashier_device_id": "cashier-test", "operator_id": "operator-1"})
            assert replacement.status_code == 200
            second = client.post("/api/v1/cashier/cashier-test/nfc-registration/complete",
                                 headers={"X-NVM-Device-Key": "cash-key"},
                                 json={"session_id": replacement.json()["session_id"], "card_uid": "04:AA:BB:CC:02", "pin": "5678"})
            assert second.status_code == 200
            new_credential = second.json()["credential_id"]
            with client.app.state.db.connect() as c:
                assert c.execute("SELECT status FROM identity_credentials WHERE credential_id=?", (old_credential,)).fetchone()["status"] == "inactive"
                assert c.execute("SELECT status FROM identity_credentials WHERE credential_id=?", (new_credential,)).fetchone()["status"] == "active"
                assert c.execute("SELECT status FROM member_nfc_cards WHERE credential_id=?", (old_credential,)).fetchone()["status"] == "revoked"
                assert c.execute("SELECT COUNT(*) FROM identity_members WHERE member_id='NTR-00004'").fetchone()[0] == 1
        finally:
            main.get_settings = old
