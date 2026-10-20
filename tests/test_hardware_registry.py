from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
import app.main as main


def test_server_key_provisions_mac_derived_device_identity():
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {
            "db_path": Path(d) / "m-group.db",
            "admin_token": "admin-secret"
        })()
        try:
            client = TestClient(main.create_app())
            headers = {"X-M-Group-Admin-Token": "admin-secret"}
            provision = client.post(
                "/api/v1/devices/provision",
                json={"device_type": "esp32-cashier"},
                headers=headers,
            )
            assert provision.status_code == 200
            payload = provision.json()
            assert payload["device_id"].startswith("pending-")
            provisioned_id = payload["device_id"]
            key = payload["device_key"]

            with client.app.state.db.connect() as conn:
                row = conn.execute(
                    "SELECT device_id,hardware_id,auth_key_hash FROM device_registry"
                ).fetchone()
                assert row["device_id"].startswith("pending-")
                assert row["hardware_id"] is None

            registration = {
                "device_type": "esp32-cashier",
                "hardware_id": "Cashier_aabbccddee01",
                "mac_address": "AA:BB:CC:DD:EE:01",
                "device_key": key,
            }
            first = client.post("/api/v1/devices/register", json=registration)
            assert first.status_code == 200
            data = first.json()
            assert data["device_id"] == provisioned_id
            assert data["hardware_id"] == "cashier_aabbccddee01"
            assert data["status"] == "active"
            assert data["registered"] is True

            repeat = client.post("/api/v1/devices/register", json=registration)
            assert repeat.status_code == 200
            assert repeat.json()["device_id"] == provisioned_id

            wrong_key = {**registration, "device_key": "wrong-secret"}
            bad = client.post("/api/v1/devices/register", json=wrong_key)
            assert bad.status_code == 403

            wrong_mac_identity = {**registration, "hardware_id": "Cashier_wrong"}
            mismatch = client.post("/api/v1/devices/register", json=wrong_mac_identity)
            assert mismatch.status_code == 400
            malformed_mac = {**registration, "mac_address": "AA:BB:CC:DD:EE:0Z"}
            assert client.post("/api/v1/devices/register", json=malformed_mac).status_code == 400

            heartbeat = client.post(
                f"/api/v1/devices/{provisioned_id}/heartbeat",
                json={"device_type": "esp32-cashier"},
                headers={"X-M-Group-Device-Key": key},
            )
            assert heartbeat.status_code == 200

            listed = client.get("/api/v1/devices", headers=headers)
            assert listed.status_code == 200
            item = next(x for x in listed.json()["devices"] if x["device_id"] == provisioned_id)
            assert item["hardware_id"] == "cashier_aabbccddee01"
            assert item["mac_address"] == "AA:BB:CC:DD:EE:01"
            assert item["status"] == "active"
        finally:
            main.get_settings = old


def test_unprovisioned_key_cannot_create_device():
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {
            "db_path": Path(d) / "m-group.db",
            "admin_token": "admin-secret"
        })()
        try:
            client = TestClient(main.create_app())
            response = client.post(
                "/api/v1/devices/register",
                json={
                    "device_type": "esp32-cashier",
                    "hardware_id": "Cashier_aabbccddee01",
                    "mac_address": "AA:BB:CC:DD:EE:01",
                    "device_key": "arbitrary-unprovisioned-key",
                },
            )
            assert response.status_code == 403
            assert response.json()["detail"] == "device_not_provisioned"
        finally:
            main.get_settings = old
