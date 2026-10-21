from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib

from fastapi.testclient import TestClient

import app.main as main


from tests.auth_helpers import login_admin
def _client_with_member(tmp_path):
    old = main.get_settings
    main.get_settings = lambda: type(
        "S", (), {"db_path": Path(tmp_path) / "m-group.db",}
    )()
    client = TestClient(main.create_app())
    with client.app.state.db.connect() as c:
        c.execute(
            "INSERT INTO device_registry(device_id,device_type,status,auth_key_hash) VALUES(?,?,?,?)",
            ("cashier-01", "esp32-cashier", "active", hashlib.sha256(b"cash-secret").hexdigest()),
        )
        c.execute("INSERT INTO identity_members(member_id,name,status) VALUES('ID-A001','Test Member','active')")
        c.execute(
            "INSERT INTO identity_credentials(credential_id,member_id,credential_type,status) VALUES(?,?,?,?)",
            ("cred-1", "ID-A001", "nfc", "active"),
        )
        c.execute(
            "INSERT INTO member_nfc_cards(card_id,member_id,credential_id,card_uid,status) VALUES(?,?,?,?,?)",
            ("card-1", "ID-A001", "cred-1", "04A1B2C3", "active"),
        )
        c.execute(
            "INSERT INTO financial_accounts(account_id,member_id,account_type,status) VALUES(?,?,?,?)",
            ("acct-1", "ID-A001", "savings", "active"),
        )
        c.execute(
            "INSERT INTO financial_ledger(account_id,direction,amount,reference) VALUES(?,?,?,?)",
            ("acct-1", "credit", 27500, "seed-balance"),
        )
        c.commit()
    return client, old


def test_device_member_balance_is_read_only_and_uses_official_ledger():
    with TemporaryDirectory() as tmp:
        client, old = _client_with_member(tmp)
        try:
            response = client.post(
                "/api/v1/devices/member-balance",
                json={"card_uid": "04A1B2C3"},
                headers={"X-M-Group-Device-Key": "cash-secret"},
            )
            assert response.status_code == 200
            assert response.json() == {
                "member_id": "ID-A001",
                "member_name": "Test Member",
                "balance": 27500,
                "currency": "IDR",
            }
            duplicate = client.post(
                "/api/v1/devices/member-balance",
                json={"card_uid": "04A1B2C3"},
                headers={"X-M-Group-Device-Key": "cash-secret"},
            )
            assert duplicate.status_code == 429
            with client.app.state.db.connect() as c:
                assert c.execute("SELECT COUNT(*) FROM financial_ledger").fetchone()[0] == 1
                assert c.execute("SELECT COUNT(*) FROM payment_transactions").fetchone()[0] == 0
        finally:
            main.get_settings = old


def test_device_member_balance_requires_valid_device_authentication():
    with TemporaryDirectory() as tmp:
        client, old = _client_with_member(tmp)
        try:
            response = client.post(
                "/api/v1/devices/member-balance",
                json={"card_uid": "04A1B2C3"},
            )
            assert response.status_code == 401
            bad_key = client.post(
                "/api/v1/devices/member-balance",
                json={"card_uid": "04A1B2C3"},
                headers={"X-M-Group-Device-Key": "wrong-key"},
            )
            assert bad_key.status_code == 403
        finally:
            main.get_settings = old


def test_device_member_balance_rejects_unknown_or_revoked_cards():
    with TemporaryDirectory() as tmp:
        client, old = _client_with_member(tmp)
        try:
            headers = {"X-M-Group-Device-Key": "cash-secret"}
            unknown = client.post(
                "/api/v1/devices/member-balance",
                json={"card_uid": "NO-SUCH-CARD"},
                headers=headers,
            )
            assert unknown.status_code == 404
            with client.app.state.db.connect() as c:
                c.execute("UPDATE member_nfc_cards SET status='revoked' WHERE card_id='card-1'")
                c.commit()
            revoked = client.post(
                "/api/v1/devices/member-balance",
                json={"card_uid": "04A1B2C3"},
                headers=headers,
            )
            assert revoked.status_code == 404
        finally:
            main.get_settings = old

def test_member_registration_generates_sequential_demo_format_id():
    with TemporaryDirectory() as tmp:
        client, old = _client_with_member(tmp)
        try:
            response = client.post(
                "/api/v1/members",
                json={"name": "Second Member", "nik": "1234567890123456"},
                headers=login_admin(client),
            )
            assert response.status_code == 200
            assert response.json()["member_id"] == "ID-A002"
            with client.app.state.db.connect() as c:
                account = c.execute(
                    "SELECT member_id,account_type,status FROM financial_accounts WHERE member_id='ID-A002'"
                ).fetchone()
                assert account is not None
                assert account["account_type"] == "savings"
                assert account["status"] == "active"
        finally:
            main.get_settings = old

def test_device_provisioning_validates_type_and_returns_one_time_key():
    with TemporaryDirectory() as tmp:
        client, old = _client_with_member(tmp)
        try:
            headers = login_admin(client)
            invalid = client.post(
                "/api/v1/devices/provision",
                json={"device_type": "unknown-device", "display_name": "Vending 02"},
                headers=headers,
            )
            assert invalid.status_code == 400
            assert invalid.json()["detail"] == "invalid_device_type"

            created = client.post(
                "/api/v1/devices/provision",
                json={"device_type": "esp32-vending", "display_name": "Vending 02"},
                headers=headers,
            )
            assert created.status_code == 200
            key = created.json()["device_key"]
            assert len(key) >= 32
            with client.app.state.db.connect() as c:
                row = c.execute(
                    "SELECT auth_key_hash,auth_key_hint FROM device_registry WHERE auth_key_hash=?",
                    (hashlib.sha256(key.encode()).hexdigest(),),
                ).fetchone()
                assert row["auth_key_hash"] != key
                assert row["auth_key_hint"] == key[-6:]
        finally:
            main.get_settings = old
