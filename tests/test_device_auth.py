from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
import app.main as main
import hashlib

from tests.auth_helpers import login_admin
def test_device_authentication_and_provisioning():
    with TemporaryDirectory() as d:
        old=main.get_settings
        main.get_settings=lambda: type("S",(),{"db_path":Path(d)/"m-group.db",})()
        try:
            client=TestClient(main.create_app())
            p=client.post("/api/v1/devices/cashier-01/provision",
                          json={"device_type":"esp32-cashier"},
                          headers=login_admin(client))
            assert p.status_code==200
            key=p.json()["device_key"]
            denied=client.post("/api/v1/devices/cashier-01/heartbeat",
                               json={"device_type":"esp32-cashier"})
            assert denied.status_code==401
            ok=client.post("/api/v1/devices/cashier-01/heartbeat",
                           json={"device_type":"esp32-cashier"},
                           headers={"X-M-Group-Device-Key":key})
            assert ok.status_code==200
            assert ok.json()["status"] == "active"

            # A device heartbeat must not be able to change its own registry status.
            status_change=client.post(
                "/api/v1/devices/cashier-01/heartbeat",
                json={"device_type":"esp32-cashier","status":"disabled"},
                headers={"X-M-Group-Device-Key":key},
            )
            assert status_change.status_code == 400
            type_change=client.post(
                "/api/v1/devices/cashier-01/heartbeat",
                json={"device_type":"esp32-s3-vending"},
                headers={"X-M-Group-Device-Key":key},
            )
            assert type_change.status_code == 409
            with client.app.state.db.connect() as c:
                row = c.execute(
                    "SELECT status,device_type FROM device_registry WHERE hardware_id='cashier-01'"
                ).fetchone()
                assert row["status"] == "active"
                assert row["device_type"] == "esp32-cashier"

            bad=client.post("/api/v1/devices/cashier-01/heartbeat",
                            json={"device_type":"esp32-cashier"},
                            headers={"X-M-Group-Device-Key":"wrong"})
            assert bad.status_code==403
        finally:
            main.get_settings=old

def test_vending_requires_device_key():
    with TemporaryDirectory() as d:
        old=main.get_settings
        main.get_settings=lambda:type("S",(),{"db_path":Path(d)/"m-group.db",})()
        try:
            client=TestClient(main.create_app())
            with client.app.state.db.connect() as c:
                c.execute("INSERT INTO device_registry(hardware_id,device_type,status,auth_key_hash) VALUES(?,?,?,?)",
                          ("vm-01","esp32-s3-vending","active",hashlib.sha256(b"vm-secret").hexdigest()))
                c.execute("INSERT INTO vending_machines(machine_id,name,status,hardware_id) VALUES(?,?,?,?)",
                          ("v1","Vending","active","vm-01"))
                c.execute("INSERT INTO identity_members(member_id,name) VALUES(?,?)",("m1","Member"))
                c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES(?,?,?)",("a1","m1","savings"))
                c.execute("INSERT INTO financial_ledger(account_id,direction,amount,reference) VALUES(?,?,?,?)",("a1","credit",10000,"seed"))
                c.execute("INSERT INTO credential_registry(credential_id,credential_type,member_id,status,enabled) VALUES(?,?,?,?,?)",("nfc1","nfc","m1","active",1))
                c.execute("INSERT INTO vending_products(product_id,machine_id,name,price,stock,slot,capacity,servo_channel) VALUES(?,?,?,?,?,?,?,?)",("p1","v1","P1",1000,1,1,1,1))
                c.commit()
            denied=client.post("/api/v1/vending/v1/transactions",
                               json={"product_id":"1","credential_id":"nfc1","idempotency_key":"x"})
            assert denied.status_code==401
            ok=client.post("/api/v1/vending/v1/transactions",
                           json={"product_id":"1","credential_id":"nfc1","idempotency_key":"x"},
                           headers={"X-M-Group-Device-Key":"vm-secret"})
            assert ok.status_code==200
            assert ok.json()["account_id"]=="a1"
        finally:
            main.get_settings=old

def test_auto_provision_waits_for_registration_and_keeps_stable_hardware_id():
    with TemporaryDirectory() as d:
        old=main.get_settings
        main.get_settings=lambda: type("S",(),{"db_path":Path(d)/"m-group.db",})()
        try:
            client=TestClient(main.create_app())
            provision=client.post(
                "/api/v1/devices/provision",
                json={"device_type":"esp32-cashier"},
                headers=login_admin(client),
            )
            assert provision.status_code == 200
            payload=provision.json()
            assert payload["hardware_id"].startswith("pending-")
            assert payload["status"] == "awaiting_device_registration"
            key=payload["device_key"]

            with client.app.state.db.connect() as c:
                before=c.execute(
                    "SELECT hardware_id,status FROM device_registry WHERE hardware_id=?",
                    (payload["hardware_id"],),
                ).fetchone()
                assert before["status"] == "awaiting_device_registration"

            registered=client.post(
                "/api/v1/devices/register",
                json={
                    "device_type":"esp32-cashier",
                    "hardware_id":"CASHIER_AABBCC112233",
                    "mac_address":"aa:bb:cc:11:22:33",
                    "device_key":key,
                },
            )
            assert registered.status_code == 200, registered.text
            body=registered.json()
            assert body["hardware_id"] == "cashier_aabbcc112233"
            assert body["hardware_id"] == payload["hardware_id"]
            assert body["status"] == "active"

            with client.app.state.db.connect() as c:
                after=c.execute(
                    "SELECT hardware_id,hardware_id,status FROM device_registry WHERE hardware_id=?",
                    (payload["hardware_id"],),
                ).fetchone()
                assert after["hardware_id"] == payload["hardware_id"]
                assert after["hardware_id"] == "cashier_aabbcc112233"
                assert after["status"] == "active"
        finally:
            main.get_settings=old

