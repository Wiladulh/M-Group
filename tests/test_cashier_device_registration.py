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
                "/api/v1/devices/cashier-01/heartbeat",
                json={"device_type": "esp32-cashier", "status": "active"},
            )
            assert missing_key.status_code == 401

            provision = client.post(
                "/api/v1/devices/cashier-01/provision",
                json={"device_type": "esp32-cashier"},
                headers=login_admin(client),
            )
            assert provision.status_code == 200
            data = provision.json()
            device_key = data["device_key"]
            assert "device_id" not in data
            assert data["device_type"] == "esp32-cashier"

            invalid_key = client.post(
                "/api/v1/devices/cashier-01/heartbeat",
                json={"device_type": "esp32-cashier", "status": "active"},
                headers={"X-M-Group-Device-Key": "invalid-key"},
            )
            assert invalid_key.status_code == 403

            heartbeat = client.post(
                "/api/v1/devices/cashier-01/heartbeat",
                json={"device_type": "esp32-cashier", "status": "active"},
                headers={"X-M-Group-Device-Key": device_key},
            )
            assert heartbeat.status_code == 200
            hb = heartbeat.json()
            assert "device_id" not in hb
            assert hb["device_type"] == "esp32-cashier"

            with Database(db_path).connect() as c:
                row = c.execute(
                    "SELECT device_id, device_type, status FROM device_registry WHERE device_id=?",
                    ("cashier-01",),
                ).fetchone()
                assert row is not None
                assert row["device_id"] == "cashier-01"
                assert row["device_type"] == "esp32-cashier"
                assert row["status"] == "active"
        finally:
            main.get_settings = old
