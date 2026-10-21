import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import app.main as main


from tests.auth_helpers import login_admin
def test_cashier_deposit_is_atomic_and_idempotency_conflicts_are_rejected():
    with TemporaryDirectory() as directory:
        old_settings = main.get_settings
        main.get_settings = lambda: type(
            "S", (), {"db_path": Path(directory) / "m-group.db",}
        )()
        try:
            client = TestClient(main.create_app())
            admin = login_admin(client)
            device_key = "cashier-test-secret"
            with client.app.state.db.connect() as c:
                c.execute(
                    "INSERT INTO device_registry(device_id,device_type,status,auth_key_hash) VALUES(?,?,?,?)",
                    ("cashier-test", "esp32-cashier", "active", hashlib.sha256(device_key.encode()).hexdigest()),
                )
                c.execute("INSERT INTO identity_members(member_id,name) VALUES('member-1','Test Member')")
                c.execute(
                    "INSERT INTO identity_credentials(credential_id,member_id,credential_type) VALUES('credential-1','member-1','nfc')"
                )
                c.execute(
                    "INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('account-1','member-1','savings')"
                )
                c.execute(
                    "INSERT INTO financial_ledger(account_id,direction,amount,reference) VALUES('account-1','credit',50000,'seed')"
                )
                c.commit()

            assert client.post("/api/v1/members/member-1/pin", headers=admin, json={
                "pin": "1234", "operator_id": "admin", "identity_verified": True, "reason": "test cashier deposit"
            }).status_code == 200
            assert client.post("/api/v1/cashier/operator-pin", headers=admin, json={"pin": "6789"}).status_code == 200

            headers = {"X-M-Group-Device-Key": device_key}
            request = {
                "credential_id": "credential-1", "amount": 10000,
                "operator_pin": "6789", "member_pin": "1234", "idempotency_key": "cashier-deposit-1",
            }
            first = client.post("/api/v1/cashier/deposits", headers=headers, json=request)
            assert first.status_code == 200, first.text
            assert "device_id" not in first.json()
            assert first.json()["balance_before"] == 50000
            assert first.json()["balance_after"] == 60000

            replay = client.post("/api/v1/cashier/deposits", headers=headers, json=request)
            assert replay.status_code == 200, replay.text
            assert "device_id" not in replay.json()
            assert replay.json()["transaction_id"] == first.json()["transaction_id"]
            assert replay.json()["financial_transaction_id"] == first.json()["financial_transaction_id"]

            conflict = client.post(
                "/api/v1/cashier/deposits", headers=headers,
                json={**request, "amount": 11000},
            )
            assert conflict.status_code == 409
            assert conflict.json()["detail"] == "idempotency_key_conflict"

            with client.app.state.db.connect() as c:
                assert c.execute("SELECT COUNT(*) FROM cashier_deposits").fetchone()[0] == 1
                assert c.execute("SELECT COUNT(*) FROM financial_transactions").fetchone()[0] == 1
                assert c.execute("SELECT COUNT(*) FROM financial_ledger WHERE account_id='account-1'").fetchone()[0] == 2
                balance = c.execute(
                    "SELECT SUM(CASE WHEN direction='credit' THEN amount ELSE -amount END) "
                    "FROM financial_ledger WHERE account_id='account-1'"
                ).fetchone()[0]
                assert balance == 60000
        finally:
            main.get_settings = old_settings
