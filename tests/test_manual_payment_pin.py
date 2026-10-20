from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
import app.main as main
from app.identity.service import IdentityService


from tests.auth_helpers import login_admin
def test_manual_nfc_payment_requires_and_verifies_member_pin():
    with TemporaryDirectory() as directory:
        old = main.get_settings
        main.get_settings = lambda: type(
            "S", (), {"db_path": Path(directory) / "m-group.db",}
        )()
        try:
            client = TestClient(main.create_app())
            db = client.app.state.db
            with db.connect() as conn:
                conn.execute("INSERT INTO identity_members(member_id,name) VALUES('member-1','Test')")
                conn.execute(
                    "INSERT INTO identity_credentials(credential_id,member_id,credential_type) VALUES('credential-1','member-1','nfc')"
                )
                conn.execute(
                    "INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('account-1','member-1','savings')"
                )
                conn.execute(
                    "INSERT INTO financial_ledger(account_id,direction,amount,reference) VALUES('account-1','credit',10000,'seed')"
                )
                conn.commit()
            IdentityService(db).set_pin("member-1", "1234")
            admin = login_admin(client)
            base = {
                "credential_id": "credential-1", "account_id": "account-1",
                "amount": 1000, "method": "NFC", "provider": "local",
                "idempotency_key": "manual-payment-1",
            }

            missing = client.post("/api/v1/payments", headers=admin, json=base)
            assert missing.status_code == 403
            assert missing.json()["detail"] == "pin_required"

            wrong = client.post("/api/v1/payments", headers=admin, json={**base, "pin": "9999"})
            assert wrong.status_code == 403
            assert wrong.json()["detail"] == "invalid_pin"

            valid = client.post("/api/v1/payments", headers=admin, json={**base, "pin": "1234"})
            assert valid.status_code == 200, valid.text
            assert valid.json()["final_amount"] == 1000
            assert client.get("/api/v1/accounts/account-1/balance", headers=admin).json()["balance"] == 9000
        finally:
            main.get_settings = old
