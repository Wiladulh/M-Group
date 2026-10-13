from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
import app.main as main
import hashlib

def test_device_authentication_and_provisioning():
    with TemporaryDirectory() as d:
        old=main.get_settings
        main.get_settings=lambda: type("S",(),{"db_path":Path(d)/"m-group.db","admin_token":"admin-secret"})()
        try:
            client=TestClient(main.create_app())
            p=client.post("/api/v1/devices/cashier-01/provision",
                          json={"device_type":"esp32-cashier"},
                          headers={"X-M-Group-Admin-Token":"admin-secret"})
            assert p.status_code==200
            key=p.json()["device_key"]
            denied=client.post("/api/v1/devices/cashier-01/heartbeat",
                               json={"device_type":"esp32-cashier"})
            assert denied.status_code==401
            ok=client.post("/api/v1/devices/cashier-01/heartbeat",
                           json={"device_type":"esp32-cashier"},
                           headers={"X-M-Group-Device-Key":key})
            assert ok.status_code==200
            bad=client.post("/api/v1/devices/cashier-01/heartbeat",
                            json={"device_type":"esp32-cashier"},
                            headers={"X-M-Group-Device-Key":"wrong"})
            assert bad.status_code==403
        finally:
            main.get_settings=old

def test_vending_requires_device_key():
    with TemporaryDirectory() as d:
        old=main.get_settings
        main.get_settings=lambda:type("S",(),{"db_path":Path(d)/"m-group.db","admin_token":"admin-secret"})()
        try:
            client=TestClient(main.create_app())
            with client.app.state.db.connect() as c:
                c.execute("INSERT INTO device_registry(device_id,device_type,status,auth_key_hash) VALUES(?,?,?,?)",
                          ("vm-01","esp32-s3-vending","active",hashlib.sha256(b"vm-secret").hexdigest()))
                c.execute("INSERT INTO vending_machines(machine_id,name,status,device_id) VALUES(?,?,?,?)",
                          ("v1","Vending","active","vm-01"))
                c.execute("INSERT INTO identity_members(member_id,name) VALUES(?,?)",("m1","Member"))
                c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES(?,?,?)",("a1","m1","savings"))
                c.execute("INSERT INTO financial_ledger(account_id,direction,amount,reference) VALUES(?,?,?,?)",("a1","credit",10000,"seed"))
                c.execute("INSERT INTO credential_registry(credential_id,credential_type,member_id,status,enabled) VALUES(?,?,?,?,?)",("nfc1","nfc","m1","active",1))
                c.execute("INSERT INTO vending_products(product_id,machine_id,name,price,stock,slot,capacity,servo_channel) VALUES(?,?,?,?,?,?,?,?)",("p1","v1","P1",1000,1,1,1,1))
                c.commit()
            denied=client.post("/api/v1/vending/v1/transactions",
                               json={"product_id":"p1","credential_id":"nfc1","idempotency_key":"x"})
            assert denied.status_code==401
            ok=client.post("/api/v1/vending/v1/transactions",
                           json={"product_id":"p1","credential_id":"nfc1","idempotency_key":"x"},
                           headers={"X-M-Group-Device-Key":"vm-secret"})
            assert ok.status_code==200
            assert ok.json()["account_id"]=="a1"
        finally:
            main.get_settings=old
