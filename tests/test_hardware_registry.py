from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
import app.main as main

def test_hardware_auto_registration_and_identity_stability():
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {
            "db_path": Path(d) / "m-group.db",
            "admin_token": "admin-secret"
        })()
        try:
            client = TestClient(main.create_app())

            first = client.post(
                "/api/v1/devices/register",
                json={
                    "device_type": "esp32-cashier",
                    "hardware_id": "Cashier2ab3u",
                    "mac_address": "aa:bb:cc:dd:ee:01",
                    "device_key": "factory-secret-01",
                },
            )
            assert first.status_code == 200
            data = first.json()
            assert data["status"] == "pending"
            assert data["registered"] is False
            assert data["device_id"].startswith("dev-")
            device_id = data["device_id"]

            repeat = client.post(
                "/api/v1/devices/register",
                json={
                    "device_type": "esp32-cashier",
                    "hardware_id": "Cashier2ab3u",
                    "mac_address": "AA:BB:CC:DD:EE:02",
                    "device_key": "factory-secret-01",
                },
            )
            assert repeat.status_code == 200
            assert repeat.json()["device_id"] == device_id
            assert repeat.json()["registered"] is True
            assert repeat.json()["mac_address"] == "AA:BB:CC:DD:EE:02"

            bad = client.post(
                "/api/v1/devices/register",
                json={
                    "device_type": "esp32-cashier",
                    "hardware_id": "Cashier2ab3u",
                    "mac_address": "AA:BB:CC:DD:EE:03",
                    "device_key": "wrong-secret",
                },
            )
            assert bad.status_code == 403

            rename = client.patch(
                f"/api/v1/devices/{device_id}",
                json={
                    "device_type": "esp32-cashier",
                    "status": "active",
                    "display_name": "Cashier Utama",
                },
                headers={"X-M-Group-Admin-Token": "admin-secret"},
            )
            assert rename.status_code == 200
            assert rename.json()["display_name"] == "Cashier Utama"
            assert rename.json()["hardware_id"] == "Cashier2ab3u"

            heartbeat = client.post(
                f"/api/v1/devices/{device_id}/heartbeat",
                json={"device_type": "esp32-cashier"},
                headers={"X-M-Group-Device-Key": "factory-secret-01"},
            )
            assert heartbeat.status_code == 200

            listed = client.get(
                "/api/v1/devices",
                headers={"X-M-Group-Admin-Token": "admin-secret"},
            )
            assert listed.status_code == 200
            item = next(x for x in listed.json()["devices"] if x["device_id"] == device_id)
            assert item["hardware_id"] == "Cashier2ab3u"
            assert item["display_name"] == "Cashier Utama"
            assert item["mac_address"] == "AA:BB:CC:DD:EE:02"
            assert item["status"] == "active"
            assert item["last_seen"] is not None
        finally:
            main.get_settings = old
