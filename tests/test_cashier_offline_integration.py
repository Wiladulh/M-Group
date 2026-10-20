from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import app.main as main


from conftest import login_admin
def test_cashier_replay_after_lost_response_is_idempotent():
    """Simulate server commit followed by a lost response during an offline period."""
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type(
            "S", (), {"db_path": Path(d) / "m-group.db",}
        )()
        try:
            client = TestClient(main.create_app())
            with client.app.state.db.connect() as c:
                c.execute("INSERT INTO identity_members(member_id,name) VALUES('m1','Member')")
                c.execute(
                    "INSERT INTO identity_credentials(credential_id,member_id,credential_type) "
                    "VALUES('cred1','m1','nfc')"
                )
                c.execute(
                    "INSERT INTO financial_accounts(account_id,member_id,account_type) "
                    "VALUES('a1','m1','savings')"
                )
                c.execute(
                    "INSERT INTO financial_ledger(account_id,direction,amount,reference) "
                    "VALUES('a1','credit',50000,'seed')"
                )
                c.commit()

            provision = client.post(
                "/api/v1/devices/cashier-01/provision",
                json={"device_type": "esp32-cashier"},
                headers=login_admin(client),
            )
            assert provision.status_code == 200
            device_key = provision.json()["device_key"]
            assert client.post("/api/v1/members/m1/pin", json={"pin": "1234", "operator_id": "test-admin", "identity_verified": True, "reason": "test identity verified"}, headers=login_admin(client)).status_code == 200
            assert client.post(
                "/api/v1/devices/cashier-01/heartbeat",
                json={"device_type": "esp32-cashier", "status": "active"},
                headers={"X-M-Group-Device-Key": device_key},
            ).status_code == 200

            payload = {
                "device_id": "cashier-01",
                "credential_id": "cred1",
                "account_id": "a1",
                "amount": 10000,
                "method": "NFC",
                "provider": "local",
                "idempotency_key": "cashier-01:offline-recovery-01",
                "pin": "1234",
            }
            headers = {"X-M-Group-Device-Key": device_key}

            # Server commits the payment, but the client loses the response.
            first = client.post("/api/v1/cashier/payments", json=payload, headers=headers)
            assert first.status_code == 200
            original_transaction_id = first.json()["transaction_id"]

            # Network returns: firmware must replay the exact same transaction key.
            recovered = client.post("/api/v1/cashier/payments", json=payload, headers=headers)
            assert recovered.status_code == 200
            assert recovered.json()["transaction_id"] == original_transaction_id

            with client.app.state.db.connect() as c:
                assert c.execute(
                    "SELECT COUNT(*) FROM payment_transactions"
                ).fetchone()[0] == 1
                assert c.execute(
                    "SELECT COUNT(*) FROM financial_ledger WHERE account_id='a1'"
                ).fetchone()[0] == 2
        finally:
            main.get_settings = old


def test_cashier_firmware_keeps_ambiguous_payment_pending_offline():
    source = (
        Path(__file__).resolve().parents[1] / "esp32" / "cashier" / "MGroupCashier.ino"
    ).read_text(encoding="utf-8")

    assert 'if(WiFi.status()!=WL_CONNECTED && !connectWifi(5000))' in source
    assert 'if(code<=0 || code>=500)' in source
    assert 'lcdShow("HASIL BELUM ADA","Ulangi PIN")' in source
    assert 'savePendingPayment(credential,amount,seq)' in source
    assert 'String(DEVICE_ID)+":"+seq' in source
    assert 'if(pendingPayment)' in source
    assert 'cashierPrefs.putString("pay_seq",seq)' in source
    assert 'cashierPrefs.putString("pay_pin"' not in source
