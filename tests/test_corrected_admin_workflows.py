from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib

from fastapi.testclient import TestClient

import app.main as main


def _client(tmp_path):
    old = main.get_settings
    main.get_settings = lambda: type(
        "S", (), {"db_path": Path(tmp_path) / "m-group.db", "admin_token": "admin-secret"}
    )()
    client = TestClient(main.create_app())
    with client.app.state.db.connect() as c:
        c.execute(
            "INSERT INTO identity_members(member_id,name,status) VALUES(?,?,?)",
            ("ID-A001", "Test Member", "active"),
        )
        c.execute(
            "INSERT INTO financial_accounts(account_id,member_id,account_type,status) VALUES(?,?,?,?)",
            ("acct-1", "ID-A001", "savings", "active"),
        )
        c.commit()
    return client, old


def test_generated_device_key_binds_first_hardware_registration_to_mac_id():
    with TemporaryDirectory() as tmp:
        client, old = _client(tmp)
        try:
            headers = {"X-M-Group-Admin-Token": "admin-secret"}
            created = client.post(
                "/api/v1/devices/provision",
                json={"device_type": "esp32-cashier"},
                headers=headers,
            )
            assert created.status_code == 200
            payload = created.json()
            assert payload["device_id"].startswith("pending-")
            provisioned_id = payload["device_id"]
            key = payload["device_key"]
            assert len(key) >= 32
            with client.app.state.db.connect() as c:
                row = c.execute(
                    "SELECT device_id,hardware_id,display_name,auth_key_hash FROM device_registry"
                ).fetchone()
                assert row["device_id"].startswith("pending-")
                assert row["hardware_id"] is None
                assert row["display_name"] == "Lokasi belum ditentukan"
                assert row["auth_key_hash"] == hashlib.sha256(key.encode()).hexdigest()

            registered = client.post(
                "/api/v1/devices/register",
                json={
                    "device_type": "esp32-cashier",
                    "hardware_id": "Cashier_aabbccddeeff",
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "device_key": key,
                },
            )
            assert registered.status_code == 200
            assert registered.json()["device_id"] == provisioned_id
            assert registered.json()["registered"] is True
            with client.app.state.db.connect() as c:
                row = c.execute(
                    "SELECT device_id,hardware_id,status FROM device_registry"
                ).fetchone()
                assert row["device_id"] == provisioned_id
                assert row["hardware_id"] == "cashier_aabbccddeeff"
                assert row["status"] == "active"
                assert c.execute("SELECT COUNT(*) FROM device_registry").fetchone()[0] == 1
        finally:
            main.get_settings = old


def test_member_list_returns_latest_payment_or_access_interaction():
    with TemporaryDirectory() as tmp:
        client, old = _client(tmp)
        try:
            with client.app.state.db.connect() as c:
                c.execute(
                    """INSERT INTO payment_transactions
                       (transaction_id,credential_id,account_id,amount,status,created_at)
                       VALUES(?,?,?,?,?,?)""",
                    ("pay-1", "cred-1", "acct-1", 12000, "completed", "2026-10-19 12:30:00"),
                )
                c.commit()
            response = client.get(
                "/api/v1/members",
                headers={"X-M-Group-Admin-Token": "admin-secret"},
            )
            assert response.status_code == 200
            member = next(x for x in response.json()["members"] if x["member_id"] == "ID-A001")
            assert member["last_interaction_at"] == "2026-10-19 12:30:00"
        finally:
            main.get_settings = old
