from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
import app.main as main

def test_cashier_and_vending_identity_handshake():
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {
            "db_path": Path(d) / "m-group.db",
            "admin_token": "admin-secret"
        })()
        try:
            client = TestClient(main.create_app())

            cashier = client.post("/api/v1/devices/handshake", json={
                "device_type": "esp32-cashier",
                "hardware_id": "Cashier10c8t",
                "mac_address": "AA:BB:CC:00:10:01",
                "device_key": "cashier-device-secret",
            })
            assert cashier.status_code == 200
            c = cashier.json()
            assert c["handshake"] == "accepted"
            assert c["status"] == "pending"
            assert c["device_type"] == "esp32-cashier"
            assert c["hardware_id"] == "Cashier10c8t"

            vending = client.post("/api/v1/devices/handshake", json={
                "device_type": "esp32-vending",
                "hardware_id": "Vending48cd1",
                "mac_address": "AA:BB:CC:00:48:01",
                "device_key": "vending-device-secret",
            })
            assert vending.status_code == 200
            v = vending.json()
            assert v["handshake"] == "accepted"
            assert v["status"] == "pending"
            assert v["device_type"] == "esp32-vending"
            assert v["hardware_id"] == "Vending48cd1"

            bad = client.post("/api/v1/devices/handshake", json={
                "device_type": "esp32-vending",
                "hardware_id": "Vending48cd1",
                "mac_address": "AA:BB:CC:00:48:99",
                "device_key": "wrong",
            })
            assert bad.status_code == 403

            devices = client.get(
                "/api/v1/devices",
                headers={"X-M-Group-Admin-Token":"admin-secret"},
            )
            assert devices.status_code == 200
            rows = devices.json()["devices"]
            assert {x["hardware_id"] for x in rows} >= {"Cashier10c8t","Vending48cd1"}
        finally:
            main.get_settings = old
