from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
import app.main as main


ADMIN = {"X-M-Group-Admin-Token": "admin-secret"}


def configured_client(directory):
    old = main.get_settings
    main.get_settings = lambda: type(
        "S", (), {"db_path": Path(directory) / "m-group.db", "admin_token": "admin-secret"}
    )()
    client = TestClient(main.create_app())
    return old, client


def provision(client, device_id, device_type):
    response = client.post(
        f"/api/v1/devices/{device_id}/provision",
        json={"device_type": device_type},
        headers=ADMIN,
    )
    assert response.status_code == 200, response.text
    return response.json()["device_key"]


def test_cashier_deposit_accepts_firmware_contract_without_device_id_header():
    with TemporaryDirectory() as directory:
        old, client = configured_client(directory)
        try:
            with client.app.state.db.connect() as c:
                c.execute("INSERT INTO identity_members(member_id,name) VALUES('m1','Member')")
                c.execute("INSERT INTO identity_credentials(credential_id,member_id,credential_type) VALUES('nfc-a1b2','m1','nfc')")
                c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('a1','m1','savings')")
                c.commit()

            key = provision(client, "cashier-01", "esp32-cashier")
            pin = client.post(
                "/api/v1/members/m1/pin",
                json={"pin": "1234", "operator_id": "test-admin", "identity_verified": True, "reason": "test identity verified"},
                headers=ADMIN,
            )
            assert pin.status_code == 200, pin.text
            operator = client.post("/api/v1/cashier/operator-pin", json={"pin": "9992"}, headers=ADMIN)
            assert operator.status_code == 200, operator.text

            response = client.post(
                "/api/v1/cashier/deposits",
                json={
                    "credential_id": "nfc-a1b2",
                    "amount": 5000,
                    "operator_pin": "9992",
                    "member_pin": "1234",
                    "idempotency_key": "cashier-01:deposit:1",
                },
                headers={"X-M-Group-Device-Key": key},
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "completed"
            assert response.json()["device_id"] == "cashier-01"
            assert client.get("/api/v1/accounts/a1/balance", headers=ADMIN).json()["balance"] == 5000
        finally:
            main.get_settings = old


def test_vending_firmware_device_id_resolves_distinct_machine_id_end_to_end():
    with TemporaryDirectory() as directory:
        old, client = configured_client(directory)
        try:
            with client.app.state.db.connect() as c:
                c.execute("INSERT INTO identity_members(member_id,name) VALUES('m1','Member')")
                c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('a1','m1','savings')")
                c.execute("INSERT INTO financial_ledger(account_id,direction,amount,reference) VALUES('a1','credit',10000,'seed')")
                c.execute("INSERT INTO credential_registry(credential_id,credential_type,member_id,status,enabled) VALUES('nfc-a1b2','nfc','m1','active',1)")
                c.execute("INSERT INTO vending_machines(machine_id,name,status,device_id) VALUES('machine-front','Front Machine','active','vm-01')")
                c.execute("INSERT INTO vending_products(product_id,machine_id,name,price,stock,enabled,slot,capacity,servo_channel) VALUES('water','machine-front','Water',5000,1,1,1,1,1)")
                c.commit()

            key = provision(client, "vm-01", "esp32-s3-vending")
            headers = {"X-M-Group-Device-Key": key}

            products = client.get("/api/v1/vending/vm-01/products", headers=headers)
            assert products.status_code == 200, products.text
            assert products.json()["machine"]["machine_id"] == "machine-front"
            assert products.json()["products"][0]["product_id"] == "1"

            begun = client.post(
                "/api/v1/vending/vm-01/transactions",
                json={"product_id": "1", "credential_id": "nfc-a1b2", "idempotency_key": "vm-01:contract-1"},
                headers=headers,
            )
            assert begun.status_code == 200, begun.text
            transaction_id = begun.json()["transaction_id"]

            authorized = client.post(f"/api/v1/vending/transactions/{transaction_id}/authorize", headers=headers)
            assert authorized.status_code == 200, authorized.text
            dispensed = client.post(
                f"/api/v1/vending/transactions/{transaction_id}/dispense",
                json={"success": True},
                headers=headers,
            )
            assert dispensed.status_code == 200, dispensed.text
            assert dispensed.json()["status"] == "completed"
            assert client.get("/api/v1/accounts/a1/balance", headers=ADMIN).json()["balance"] == 5000
        finally:
            main.get_settings = old
