from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient

import app.main as main
from app.core.db import Database


from tests.auth_helpers import login_admin
def test_cashier_device_registration_and_heartbeat_gate():
    with TemporaryDirectory() as d:
        old = main.get_settings
        db_path = Path(d) / "m-group.db"
        main.get_settings = lambda: type("S", (), {"db_path": db_path,})()
        try:
            client = TestClient(main.create_app())

            missing_key = client.post(
                "/api/v1/devices/heartbeat",
                json={"device_type": "esp32-cashier", "status": "active"},
            )
            assert missing_key.status_code == 401

            provision = client.post(
                "/api/v1/devices/provision",
                json={"device_type": "esp32-cashier", "display_name": "Cashier Registration"},
                headers=login_admin(client),
            )
            assert provision.status_code == 200
            data = provision.json()
            device_key = data["device_key"]
            assert "device_id" not in data
            registration = client.post(
                "/api/v1/devices/register",
                json={"device_type": "esp32-cashier", "mac_address": "AA:BB:CC:00:10:83", "device_key": device_key},
            )
            assert registration.status_code == 200, registration.text
            assert data["device_type"] == "esp32-cashier"

            invalid_key = client.post(
                "/api/v1/devices/heartbeat",
                json={"device_type": "esp32-cashier", "status": "active"},
                headers={"X-M-Group-Device-Key": "invalid-key"},
            )
            assert invalid_key.status_code == 403

            heartbeat = client.post(
                "/api/v1/devices/heartbeat",
                json={"device_type": "esp32-cashier", "status": "active"},
                headers={"X-M-Group-Device-Key": device_key},
            )
            assert heartbeat.status_code == 200
            hb = heartbeat.json()
            assert "device_id" not in hb
            assert hb["device_type"] == "esp32-cashier"

            with Database(db_path).connect() as c:
                row = c.execute(
                    "SELECT device_type, status FROM device_registry WHERE auth_key_hash=?",
                    (__import__("hashlib").sha256(device_key.encode()).hexdigest(),),
                ).fetchone()
                assert row is not None
                assert row["device_type"] == "esp32-cashier"
                assert row["status"] == "active"
        finally:
            main.get_settings = old
