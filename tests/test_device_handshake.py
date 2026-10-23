from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import app.main as main
from tests.auth_helpers import login_admin


def test_server_issued_keys_register_without_hardware_identity():
    with TemporaryDirectory() as directory:
        previous_settings = main.get_settings
        main.get_settings = lambda: type("Settings", (), {
            "db_path": Path(directory) / "m-group.db",
        })()
        try:
            client = TestClient(main.create_app())
            admin_headers = login_admin(client)

            for requested_type, expected_type in (
                ("esp32-cashier", "esp32-cashier"),
                ("esp32-vending", "esp32-s3-vending"),
            ):
                provision = client.post(
                    "/api/v1/devices/provision",
                    json={"device_type": requested_type},
                    headers=admin_headers,
                )
                assert provision.status_code == 200
                provisioned = provision.json()
                assert "device_key" in provisioned
                assert "device_id" not in provisioned
                assert "hardware_id" not in provisioned
                assert "mac_address" not in provisioned

                register = client.post(
                    "/api/v1/devices/register",
                    json={
                        "device_type": expected_type,
                        "device_key": provisioned["device_key"],
                    },
                )
                assert register.status_code == 200
                registered = register.json()
                assert registered == {
                    "device_type": expected_type,
                    "status": "active",
                    "registered": True,
                }
                assert "device_id" not in registered
                assert "hardware_id" not in registered

                heartbeat = client.post(
                    "/api/v1/devices/heartbeat",
                    json={"device_type": expected_type, "status": "active"},
                    headers={"X-M-Group-Device-Key": provisioned["device_key"]},
                )
                assert heartbeat.status_code == 200
                assert "device_id" not in heartbeat.json()

            invalid = client.post(
                "/api/v1/devices/register",
                json={"device_type": "cashier", "device_key": "not-a-valid-key"},
            )
            assert invalid.status_code == 403

            legacy = client.post(
                "/api/v1/devices/handshake",
                json={"device_type": "cashier", "device_key": "not-a-valid-key"},
            )
            assert legacy.status_code == 404

            with client.app.state.db.connect() as connection:
                event_count = connection.execute(
                    "SELECT COUNT(*) FROM device_events WHERE event_type='credential_registration'"
                ).fetchone()[0]
                assert event_count == 2
        finally:
            main.get_settings = previous_settings
