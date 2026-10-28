from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
import app.main as main


from tests.auth_helpers import login_admin
def test_cashier_heartbeat_and_nfc_payment():
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {"db_path": Path(d) / "m-group.db",})()
        try:
            client = TestClient(main.create_app())
            with client.app.state.db.connect() as c:
                c.execute("INSERT INTO identity_members(member_id,name) VALUES('m1','Member')")
                c.execute("INSERT INTO identity_credentials(credential_id,member_id,credential_type) VALUES('cred1','m1','nfc')")
                c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('a1','m1','savings')")
                c.execute("INSERT INTO financial_ledger(account_id,direction,amount,reference) VALUES('a1','credit',50000,'seed')")
                c.commit()

            provision = client.post(
                "/api/v1/devices/cashier-01/provision",
                json={"device_type": "esp32-cashier"},
                headers=login_admin(client),
            )
            assert provision.status_code == 200
            device_key = provision.json()["device_key"]

            assert client.post("/api/v1/members/m1/pin", json={"pin": "1234", "operator_id": "test-admin", "identity_verified": True, "reason": "test identity verified"}, headers=login_admin(client)).status_code == 200
            h = client.post(
                "/api/v1/devices/cashier-01/heartbeat",
                json={"device_type": "esp32-cashier", "status": "active"},
                headers={"X-M-Group-Device-Key": device_key},
            )
            assert h.status_code == 200

            q = {
                "credential_id": "cred1", "account_id": "a1",
                "amount": 10000, "method": "NFC", "provider": "local",
                "idempotency_key": "cashier-01:1", "pin": "1234"
            }
            p = client.post("/api/v1/cashier/payments", json=q, headers={"X-M-Group-Device-Key": device_key})
            assert p.status_code == 200
            assert "hardware_id" not in p.json()

            again = client.post("/api/v1/cashier/payments", json=q, headers={"X-M-Group-Device-Key": device_key})
            assert again.status_code == 200
            assert again.json()["transaction_id"] == p.json()["transaction_id"]

            with client.app.state.db.connect() as c:
                assert c.execute("SELECT COUNT(*) FROM payment_transactions").fetchone()[0] == 1
                assert "hardware_id" not in {row[1] for row in c.execute("PRAGMA table_info(payment_transactions)")}
        finally:
            main.get_settings = old
