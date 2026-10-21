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
            admin=login_admin(client)
            provision=client.post(
                "/api/v1/devices/provision",
                json={"device_type":"esp32-cashier","display_name":"Cashier Utama"},
                headers=admin,
            )
            assert provision.status_code==200, provision.text
            key=provision.json()["device_key"]
            denied=client.post("/api/v1/devices/heartbeat",json={"device_type":"esp32-cashier"})
            assert denied.status_code==401
            ok=client.post("/api/v1/devices/heartbeat",
                           json={"device_type":"esp32-cashier","status":"active"},
                           headers={"X-M-Group-Device-Key":key})
            assert ok.status_code==200
            assert ok.json()["status"] == "active"

            status_change=client.post(
                "/api/v1/devices/heartbeat",
                json={"device_type":"esp32-cashier","status":"disabled"},
                headers={"X-M-Group-Device-Key":key},
            )
            assert status_change.status_code == 400
            type_change=client.post(
                "/api/v1/devices/heartbeat",
                json={"device_type":"esp32-s3-vending","status":"active"},
                headers={"X-M-Group-Device-Key":key},
            )
            assert type_change.status_code == 409
            key_hash=hashlib.sha256(key.encode()).hexdigest()
            with client.app.state.db.connect() as c:
                row = c.execute(
                    "SELECT status,device_type FROM device_registry WHERE auth_key_hash=?",
                    (key_hash,),
                ).fetchone()
                assert row["status"] == "active"
                assert row["device_type"] == "esp32-cashier"

            bad=client.post("/api/v1/devices/heartbeat",
                            json={"device_type":"esp32-cashier","status":"active"},
                            headers={"X-M-Group-Device-Key":"wrong"})
            assert bad.status_code==403
        finally:
            main.get_settings=old

def test_auto_provision_requires_device_location():
    with TemporaryDirectory() as d:
        old=main.get_settings
        main.get_settings=lambda: type("S",(),{"db_path":Path(d)/"m-group.db",})()
        try:
            client=TestClient(main.create_app())
            response=client.post(
                "/api/v1/devices/provision",
                json={"device_type":"esp32-cashier"},
                headers=login_admin(client),
            )
            assert response.status_code == 400
            assert response.json()["detail"] == "device_location_required"
        finally:
            main.get_settings=old



def test_vending_provision_creates_inventory_machine_with_location():
    with TemporaryDirectory() as d:
        old=main.get_settings
        main.get_settings=lambda: type("S",(),{"db_path":Path(d)/"m-group.db",})()
        try:
            client=TestClient(main.create_app())
            admin=login_admin(client)
            provision=client.post(
                "/api/v1/devices/provision",
                json={"device_type":"esp32-s3-vending","display_name":"Vending Lantai 1"},
                headers=admin,
            )
            assert provision.status_code == 200, provision.text
            key_hash=hashlib.sha256(provision.json()["device_key"].encode()).hexdigest()
            with client.app.state.db.connect() as c:
                machine=c.execute(
                    """SELECT machine_id,name,location,device_id,status FROM vending_machines
                       WHERE device_id=(SELECT device_id FROM device_registry WHERE auth_key_hash=?)""",
                    (key_hash,),
                ).fetchone()
                assert machine is not None
                assert machine["name"] == "Vending Lantai 1"
                assert machine["location"] == "Vending Lantai 1"
                assert machine["status"] == "active"
            listed=client.get("/api/v1/vending",headers=admin)
            assert listed.status_code == 200
            assert any(x["location"] == "Vending Lantai 1" for x in listed.json()["machines"])

            registered=client.post(
                "/api/v1/devices/register",
                json={
                    "device_type":"esp32-s3-vending",
                    "mac_address":"AA:BB:CC:11:22:33",
                    "device_key":provision.json()["device_key"],
                },
            )
            assert registered.status_code == 200, registered.text
            assert "device_id" not in registered.json()
            self_catalog=client.get(
                "/api/v1/vending/self/products",
                headers={"X-M-Group-Device-Key":provision.json()["device_key"]},
            )
            assert self_catalog.status_code == 200, self_catalog.text
            assert self_catalog.json()["machine"]["location"] == "Vending Lantai 1"
        finally:
            main.get_settings=old


def test_vending_requires_device_key():
    with TemporaryDirectory() as d:
        old=main.get_settings
        main.get_settings=lambda:type("S",(),{"db_path":Path(d)/"m-group.db",})()
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
                               json={"product_id":"1","credential_id":"nfc1","idempotency_key":"x"})
            assert denied.status_code==401
            ok=client.post("/api/v1/vending/v1/transactions",
                           json={"product_id":"1","credential_id":"nfc1","idempotency_key":"x"},
                           headers={"X-M-Group-Device-Key":"vm-secret"})
            assert ok.status_code==200
            assert ok.json()["account_id"]=="a1"
        finally:
            main.get_settings=old

def test_auto_provision_registers_by_key_without_exposing_device_id():
    with TemporaryDirectory() as d:
        old=main.get_settings
        main.get_settings=lambda: type("S",(),{"db_path":Path(d)/"m-group.db",})()
        try:
            client=TestClient(main.create_app())
            provision=client.post(
                "/api/v1/devices/provision",
                json={"device_type":"esp32-cashier","display_name":"Cashier Kantin"},
                headers=login_admin(client),
            )
            assert provision.status_code == 200
            payload=provision.json()
            assert "device_id" not in payload
            assert "hardware_id" not in payload
            assert payload["status"] == "awaiting_device_registration"
            assert payload["display_name"] == "Cashier Kantin"
            key=payload["device_key"]
            key_hash=hashlib.sha256(key.encode()).hexdigest()

            with client.app.state.db.connect() as c:
                before=c.execute(
                    "SELECT device_id,status FROM device_registry WHERE auth_key_hash=?",
                    (key_hash,),
                ).fetchone()
                assert before["device_id"].startswith("pending-")
                assert before["status"] == "awaiting_device_registration"

            registered=client.post(
                "/api/v1/devices/register",
                json={
                    "device_type":"esp32-cashier",
                    "mac_address":"AA:BB:CC:11:22:33",
                    "device_key":key,
                },
            )
            assert registered.status_code == 200, registered.text
            body=registered.json()
            assert "device_id" not in body
            assert "hardware_id" not in body
            assert body["status"] == "active"
            assert body["display_name"] == "Cashier Kantin"

            heartbeat=client.post(
                "/api/v1/devices/heartbeat",
                json={"device_type":"esp32-cashier","status":"active"},
                headers={"X-M-Group-Device-Key":key},
            )
            assert heartbeat.status_code == 200, heartbeat.text
            with client.app.state.db.connect() as c:
                after=c.execute(
                    "SELECT device_id,status FROM device_registry WHERE auth_key_hash=?",
                    (key_hash,),
                ).fetchone()
                assert after["device_id"] == before["device_id"]
                assert after["status"] == "active"
        finally:
            main.get_settings=old
