from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
import hashlib
import app.main as main

def seed(client):
    with client.app.state.db.connect() as c:
        c.execute("INSERT INTO identity_members(member_id,name) VALUES('m1','Member')")
        c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('a1','m1','savings')")
        c.execute("INSERT INTO financial_ledger(account_id,direction,amount,reference) VALUES('a1','credit',10000,'seed')")
        c.execute("INSERT INTO device_registry(device_id,device_type,status,auth_key_hash) VALUES('vm-01','esp32-s3-vending','active',?)",
                  (hashlib.sha256(b'vm-secret').hexdigest(),))
        c.execute("INSERT INTO vending_machines(machine_id,name,status,device_id) VALUES('v1','Vending 1','active','vm-01')")
        c.execute("INSERT INTO vending_products(product_id,machine_id,name,price,stock) VALUES('water','v1','Water',5000,1)")
        c.execute("INSERT INTO credential_registry(credential_id,credential_type,member_id,status,enabled) VALUES('nfc1','nfc','m1','active',1)")
        c.commit()

def test_vending_api_payment_and_dispense():
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {"db_path": Path(d) / "m-group.db", "admin_token": "admin-secret"})()
        try:
            client = TestClient(main.create_app())
            seed(client)
            products = client.get("/api/v1/vending/v1/products", headers={"X-M-Group-Device-Key":"vm-secret"})
            assert products.status_code == 200
            assert products.json()["products"][0]["stock"] == 1
            assert products.json()["products"][0]["enabled"] is True
            assert products.json()["products"][0]["base_price"] == 5000
            assert products.json()["products"][0]["effective_price"] == 5000
            assert products.json()["products"][0]["discount_amount"] == 0
            tx = client.post("/api/v1/vending/v1/transactions", json={
                "product_id":"water","credential_id":"nfc1","account_id":"a1",
                "idempotency_key":"vend-api-1"} , headers={"X-M-Group-Device-Key":"vm-secret"})
            assert tx.status_code == 200
            tid = tx.json()["transaction_id"]
            auth = client.post(f"/api/v1/vending/transactions/{tid}/authorize", headers={"X-M-Group-Device-Key":"vm-secret"})
            assert auth.status_code == 200
            assert auth.json()["status"] == "authorized"
            done = client.post(f"/api/v1/vending/transactions/{tid}/dispense", json={"success":True}, headers={"X-M-Group-Device-Key":"vm-secret"})
            assert done.status_code == 200
            assert done.json()["status"] == "completed"
            # A retry after a lost HTTP response is idempotent.
            retry = client.post(f"/api/v1/vending/transactions/{tid}/dispense", json={"success":True}, headers={"X-M-Group-Device-Key":"vm-secret"})
            assert retry.status_code == 200
            assert retry.json()["status"] == "completed"
            assert client.get("/api/v1/accounts/a1/balance", headers={"X-M-Group-Admin-Token":"admin-secret"}).json()["balance"] == 5000
            assert client.get("/api/v1/vending/v1/products", headers={"X-M-Group-Device-Key":"vm-secret"}).json()["products"][0]["stock"] == 0
        finally:
            main.get_settings = old

def test_vending_api_failed_dispense_refunds():
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {"db_path": Path(d) / "m-group.db"})()
        try:
            client = TestClient(main.create_app())
            seed(client)
            tx = client.post("/api/v1/vending/v1/transactions", json={
                "product_id":"water","credential_id":"nfc1","account_id":"a1",
                "idempotency_key":"vend-api-fail"}, headers={"X-M-Group-Device-Key":"vm-secret"}).json()
            tid = tx["transaction_id"]
            assert client.post(f"/api/v1/vending/transactions/{tid}/authorize", headers={"X-M-Group-Device-Key":"vm-secret"}).status_code == 200
            failed = client.post(f"/api/v1/vending/transactions/{tid}/dispense", json={"success":False}, headers={"X-M-Group-Device-Key":"vm-secret"})
            assert failed.status_code == 200
            assert failed.json()["status"] == "refunded"
            assert failed.json()["dispense_status"] == "failed"
            assert client.get("/api/v1/accounts/a1/balance", headers={"X-M-Group-Admin-Token":"admin-secret"}).json()["balance"] == 10000
            assert client.get("/api/v1/vending/v1/products", headers={"X-M-Group-Device-Key":"vm-secret"}).json()["products"][0]["stock"] == 1
        finally:
            main.get_settings = old

def test_vending_credential_resolves_primary_savings_account():
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {"db_path": Path(d) / "m-group.db"})()
        try:
            client = TestClient(main.create_app())
            seed(client)
            result = client.get("/api/v1/credentials/nfc1/account", headers={"X-M-Group-Admin-Token":"admin-secret"})
            assert result.status_code == 200
            assert result.json()["account_id"] == "a1"
            assert result.json()["member_id"] == "m1"
        finally:
            main.get_settings = old


def test_vending_status_reconciliation_requires_device_auth_and_returns_terminal_state():
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {"db_path": Path(d) / "m-group.db"})()
        try:
            client = TestClient(main.create_app())
            seed(client)
            tx = client.post("/api/v1/vending/v1/transactions", json={
                "product_id":"water","credential_id":"nfc1","account_id":"a1",
                "idempotency_key":"vend-reconcile-1"
            }, headers={"X-M-Group-Device-Key":"vm-secret"}).json()
            tid = tx["transaction_id"]
            missing_auth = client.get(f"/api/v1/vending/transactions/{tid}")
            assert missing_auth.status_code == 401
            headers = {"X-M-Group-Device-Key":"vm-secret"}
            pending = client.get(f"/api/v1/vending/transactions/{tid}", headers=headers)
            assert pending.status_code == 200
            assert pending.json()["status"] == "pending"
            authorized = client.post(f"/api/v1/vending/transactions/{tid}/authorize", headers=headers)
            assert authorized.status_code == 200
            terminal = client.get(f"/api/v1/vending/transactions/{tid}", headers=headers)
            assert terminal.status_code == 200
            assert terminal.json()["status"] == "authorized"
        finally:
            main.get_settings = old


def test_vending_idempotency_key_cannot_be_reused_for_different_product():
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {"db_path": Path(d) / "m-group.db"})()
        try:
            client = TestClient(main.create_app())
            seed(client)
            headers = {"X-M-Group-Device-Key":"vm-secret"}
            first = client.post("/api/v1/vending/v1/transactions", json={
                "product_id":"water","credential_id":"nfc1","account_id":"a1",
                "idempotency_key":"vend-reused-key"
            }, headers=headers)
            assert first.status_code == 200
            conflict = client.post("/api/v1/vending/v1/transactions", json={
                "product_id":"different-product","credential_id":"nfc1","account_id":"a1",
                "idempotency_key":"vend-reused-key"
            }, headers=headers)
            assert conflict.status_code == 400
            assert conflict.json()["detail"] == "idempotency_key_conflict"
        finally:
            main.get_settings = old
