from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient

import app.main as main
from app.core.db import Database


def test_cashier_payment_requires_active_registered_device():
    with TemporaryDirectory() as d:
        old = main.get_settings
        db_path = Path(d) / "nvm.db"
        main.get_settings = lambda: type("S", (), {"db_path": db_path, "admin_token": "admin-secret"})()
        try:
            client = TestClient(main.create_app())
            with Database(db_path).connect() as c:
                c.execute("INSERT INTO identity_members(member_id,name) VALUES('member-1','Test')")
                c.execute(
                    "INSERT INTO identity_credentials(credential_id,member_id,credential_type) "
                    "VALUES('test-credential-01','member-1','nfc')"
                )
                c.execute(
                    "INSERT INTO financial_accounts(account_id,member_id,account_type) "
                    "VALUES('member-account-01','member-1','savings')"
                )
                c.execute(
                    "INSERT INTO financial_ledger(account_id,direction,amount,reference) "
                    "VALUES('member-account-01','credit',10000,'seed')"
                )

            assert client.post("/api/v1/members/member-1/pin", json={"pin": "1234", "operator_id": "test-admin"}, headers={"X-NVM-Admin-Token": "admin-secret"}).status_code == 200

            q = {
                "device_id": "cashier-01",
                "credential_id": "test-credential-01",
                "account_id": "member-account-01",
                "amount": 1000,
                "method": "NFC",
                "provider": "local",
                "idempotency_key": "cashier-01:1",
                "pin": "1234",
            }
            assert client.post("/api/v1/cashier/payments", json=q).status_code == 401

            provision = client.post(
                "/api/v1/devices/cashier-01/provision",
                json={"device_type": "esp32-cashier"},
                headers={"X-NVM-Admin-Token": "admin-secret"},
            )
            assert provision.status_code == 200
            device_key = provision.json()["device_key"]

            hb = client.post(
                "/api/v1/devices/cashier-01/heartbeat",
                json={"device_type": "esp32-cashier", "status": "active"},
                headers={"X-NVM-Device-Key": device_key},
            )
            assert hb.status_code == 200

            payment = client.post(
                "/api/v1/cashier/payments",
                json=q,
                headers={"X-NVM-Device-Key": device_key},
            )
            assert payment.status_code == 200
            assert payment.json()["status"] == "completed"
            assert payment.json()["device_id"] == "cashier-01"
        finally:
            main.get_settings = old
