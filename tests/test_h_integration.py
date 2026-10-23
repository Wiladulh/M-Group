from pathlib import Path
from tempfile import TemporaryDirectory
import app.main as main
from fastapi.testclient import TestClient


from tests.auth_helpers import login_admin
def test_h_full_integration_one_by_one():
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type(
            "S", (), {"db_path": Path(d) / "m-group.db",}
        )()
        try:
            client = TestClient(main.create_app())
            admin = login_admin(client)

            # H-01 Member/KTP
            member = client.post(
                "/api/v1/members",
                headers=admin,
                json={
                    "name": "H Test Member",
                    "nik": "TEST-NIK-001",
                    "birth_place": "Lamongan",
                    "birth_date": "1990-01-01",
                    "sex": "Laki-laki",
                    "address": "H Test Address",
                    "citizenship": "WNI",
                },
            )
            assert member.status_code == 200
            member_id = member.json()["member_id"]
            assert member.json()["nik"] == "TEST-NIK-001"

            # H-02 Member -> Cashier
            provision = client.post(
                "/api/v1/devices/cashier-h/provision",
                headers=admin,
                json={"device_type": "esp32-cashier"},
            )
            assert provision.status_code == 200
            cashier_key = provision.json()["device_key"]

            heartbeat = client.post(
                "/api/v1/devices/cashier-h/heartbeat",
                headers={"X-M-Group-Device-Key": cashier_key},
                json={"device_type": "esp32-cashier", "status": "active"},
            )
            assert heartbeat.status_code == 200

            # H-03 NFC registration
            session = client.post(
                f"/api/v1/members/{member_id}/nfc-registration/start",
                headers=admin,
                json={"cashier_device_id": "cashier-h"},
            )
            assert session.status_code == 200
            session_id = session.json()["session_id"]

            pending = client.get(
                f"/api/v1/members/{member_id}/nfc-registration/{session_id}",
                headers=admin,
            )
            assert pending.status_code == 200
            assert pending.json()["status"] == "scan_pending"

            cashier_pending = client.get(
                "/api/v1/cashier/cashier-h/nfc-registration",
                headers={"X-M-Group-Device-Key": cashier_key},
            )
            assert cashier_pending.status_code == 200
            assert cashier_pending.json()["session_id"] == session_id

            complete = client.post(
                "/api/v1/cashier/cashier-h/nfc-registration/complete",
                headers={"X-M-Group-Device-Key": cashier_key},
                json={"session_id": session_id, "card_uid": "04:A1:B2:C3:D4", "pin": "1234"},
            )
            assert complete.status_code == 200
            credential_id = complete.json()["credential_id"]

            # Create the member's savings account and seed balance.
            with client.app.state.db.connect() as c:
                c.execute(
                    "INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES(?,?,?)",
                    ("acct-h", member_id, "savings"),
                )
                c.execute(
                    "INSERT INTO financial_ledger(account_id,direction,amount,reference) VALUES(?,?,?,?)",
                    ("acct-h", "credit", 20000, "h-seed"),
                )
                c.commit()

            # H-04 NFC payment
            payment = client.post(
                "/api/v1/payments",
                headers=admin,
                json={
                    "credential_id": credential_id,
                    "account_id": "acct-h",
                    "amount": 5000,
                    "method": "NFC",
                    "provider": "local",
                    "pin": "1234",
                    "idempotency_key": "h-nfc-1",
                },
            )
            assert payment.status_code == 200
            assert payment.json()["final_amount"] == 5000

            # H-05 Ledger/saldo
            balance = client.get("/api/v1/accounts/acct-h/balance", headers=admin)
            assert balance.status_code == 200
            assert balance.json()["balance"] == 15000

            # H-06 Cashier
            cashier_payment = client.post(
                "/api/v1/cashier/payments",
                headers={"X-M-Group-Device-Key": cashier_key},
                json={
                    "device_id": "cashier-h",
                    "credential_id": credential_id,
                    "account_id": "acct-h",
                    "amount": 2000,
                    "method": "NFC",
                    "provider": "local",
                    "pin": "1234",
                    "idempotency_key": "h-cashier-1",
                },
            )
            assert cashier_payment.status_code == 200
            assert "device_id" not in cashier_payment.json()

            # H-07 Vending
            vending = client.post(
                "/api/v1/devices/vending-h/provision",
                headers=admin,
                json={"device_type": "esp32-s3-vending"},
            )
            assert vending.status_code == 200
            vending_key = vending.json()["device_key"]

            with client.app.state.db.connect() as c:
                c.execute(
                    "INSERT INTO vending_machines(machine_id,name,status,device_id) VALUES(?,?,?,?)",
                    ("machine-h", "H Vending", "active", "vending-h"),
                )
                c.execute(
                    "INSERT INTO vending_products(product_id,machine_id,name,price,stock,slot,capacity,servo_channel) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    ("water-h", "machine-h", "Water H", 3000, 1, 1, 10, 1),
                )
                c.commit()

            tx = client.post(
                "/api/v1/vending/machine-h/transactions",
                headers={"X-M-Group-Device-Key": vending_key},
                json={
                    "product_id": "1",
                    "credential_id": credential_id,
                    "account_id": "acct-h",
                    "idempotency_key": "h-vending-1",
                },
            )
            assert tx.status_code == 200
            tid = tx.json()["transaction_id"]

            authorized = client.post(
                f"/api/v1/vending/transactions/{tid}/authorize",
                headers={"X-M-Group-Device-Key": vending_key},
            )
            assert authorized.status_code == 200
            assert authorized.json()["status"] == "authorized"

            dispensed = client.post(
                f"/api/v1/vending/transactions/{tid}/dispense",
                headers={"X-M-Group-Device-Key": vending_key},
                json={"success": True},
            )
            assert dispensed.status_code == 200
            assert dispensed.json()["status"] == "completed"

            # H-08 Devices
            devices = client.get("/api/v1/devices", headers=admin)
            assert devices.status_code == 200
            ids = {x["device_id"] for x in devices.json()["devices"]}
            assert {"cashier-h", "vending-h"} <= ids

            # H-09 WebUI
            root = client.get("/")
            assert root.status_code == 200
            assert "M-Group" in root.text
            dashboard = client.get("/api/v1/dashboard", headers=admin)
            assert dashboard.status_code == 200
            assert any(x["member_id"] == member_id for x in dashboard.json()["members"])

            # H-10 Error/authorization flow
            client.cookies.clear()
            client.cookies.set("m_group_session", "invalid-session")
            assert client.get("/api/v1/members").status_code == 401
            assert client.get("/api/v1/devices").status_code == 401
            client.cookies.clear()
            admin = login_admin(client)
            assert client.get(
                "/api/v1/cashier/cashier-h/nfc-registration",
                headers={"X-M-Group-Device-Key": "wrong"},
            ).status_code == 403
            assert client.post(
                "/api/v1/vending/machine-h/transactions",
                json={
                    "product_id": "1",
                    "credential_id": credential_id,
                    "idempotency_key": "h-vending-auth-fail",
                },
            ).status_code == 401

            # Final ledger invariant after all successful debits: 20,000 - 5,000 - 2,000 - 3,000.
            assert client.get("/api/v1/accounts/acct-h/balance", headers=admin).json()["balance"] == 10000
        finally:
            main.get_settings = old
