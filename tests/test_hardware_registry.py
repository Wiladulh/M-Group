from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
import app.main as main


from tests.auth_helpers import login_admin
def test_server_key_registers_device_without_exposing_internal_reference():
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {
            "db_path": Path(d) / "m-group.db",})()
        try:
            client = TestClient(main.create_app())
            headers = login_admin(client)
            provision = client.post(
                "/api/v1/devices/provision",
                json={"device_type": "esp32-cashier", "display_name": "Cashier depan"},
                headers=headers,
            )
            assert provision.status_code == 200
            payload = provision.json()
            assert "device_id" not in payload
            assert "hardware_id" not in payload
            key = payload["device_key"]
            key_hash = __import__("hashlib").sha256(key.encode()).hexdigest()

            with client.app.state.db.connect() as conn:
                row = conn.execute(
                    "SELECT device_id,internal_ref,auth_key_hash FROM device_registry WHERE auth_key_hash=?",
                    (key_hash,),
                ).fetchone()
                assert row["device_id"].startswith("pending-")
                assert row["internal_ref"].startswith("dev_")
                assert len(row["internal_ref"]) == 36
                provisioned_id = row["device_id"]

            registration = {
                "device_type": "esp32-cashier",
                "mac_address": "AA:BB:CC:DD:EE:01",
                "device_key": key,
            }
            first = client.post("/api/v1/devices/register", json=registration)
            assert first.status_code == 200
            data = first.json()
            assert "device_id" not in data
            assert "hardware_id" not in data
            assert data["status"] == "active"
            assert data["registered"] is True

            repeat = client.post("/api/v1/devices/register", json=registration)
            assert repeat.status_code == 200
            assert "device_id" not in repeat.json()

            wrong_key = {**registration, "device_key": "wrong-secret"}
            bad = client.post("/api/v1/devices/register", json=wrong_key)
            assert bad.status_code == 403

            wrong_mac_identity = {**registration, "mac_address": "AA:BB:CC:DD:EE:02"}
            mismatch = client.post("/api/v1/devices/register", json=wrong_mac_identity)
            assert mismatch.status_code == 409
            malformed_mac = {**registration, "mac_address": "AA:BB:CC:DD:EE:0Z"}
            assert client.post("/api/v1/devices/register", json=malformed_mac).status_code == 400

            heartbeat = client.post(
                "/api/v1/devices/heartbeat",
                json={"device_type": "esp32-cashier", "status": "active"},
                headers={"X-M-Group-Device-Key": key},
            )
            assert heartbeat.status_code == 200

            listed = client.get("/api/v1/devices", headers=headers)
            assert listed.status_code == 200
            item = next(x for x in listed.json()["devices"] if x["device_key_hint"] == __import__("hashlib").sha256(key.encode()).hexdigest()[:12])
            assert "device_id" not in item
            assert "device_ref" not in item
            assert client.get(f"/api/v1/devices/{provisioned_id}", headers=headers).status_code == 404
            assert client.post(
                f"/api/v1/devices/{provisioned_id}/heartbeat",
                json={"device_type": "esp32-cashier"},
                headers={"X-M-Group-Device-Key": key},
            ).status_code == 404
            assert item["mac_address"] == "AA:BB:CC:DD:EE:01"
            assert item["status"] == "active"
        finally:
            main.get_settings = old


def test_unprovisioned_key_cannot_create_device():
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {
            "db_path": Path(d) / "m-group.db",})()
        try:
            client = TestClient(main.create_app())
            response = client.post(
                "/api/v1/devices/register",
                json={
                    "device_type": "esp32-cashier",
                    "mac_address": "AA:BB:CC:DD:EE:01",
                    "device_key": "arbitrary-unprovisioned-key",
                },
            )
            assert response.status_code == 403
            assert response.json()["detail"] == "device_not_provisioned"
        finally:
            main.get_settings = old



def test_device_management_and_dashboard_never_expose_internal_device_ids():
    with TemporaryDirectory() as directory:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {"db_path": Path(directory) / "m-group.db"})()
        try:
            client = TestClient(main.create_app())
            admin = login_admin(client)
            provision = client.post(
                "/api/v1/devices/provision",
                headers=admin,
                json={"device_type": "esp32-cashier", "display_name": "Cashier Utama"},
            )
            assert provision.status_code == 200, provision.text
            key = provision.json()["device_key"]
            hint = __import__("hashlib").sha256(key.encode()).hexdigest()[:12]
            with client.app.state.db.connect() as conn:
                internal = conn.execute(
                    "SELECT device_id FROM device_registry WHERE auth_key_hash=?",
                    (__import__("hashlib").sha256(key.encode()).hexdigest(),),
                ).fetchone()
                assert internal is not None
                internal_id = internal["device_id"]

            listed = client.get("/api/v1/devices", headers=admin)
            assert listed.status_code == 200, listed.text
            row = next(item for item in listed.json()["devices"] if item["device_key_hint"] == hint)
            assert "device_id" not in row
            assert "device_ref" not in row

            fetched = client.get(f"/api/v1/devices/by-key-hint/{hint}", headers=admin)
            assert fetched.status_code == 200, fetched.text
            assert "device_id" not in fetched.json()
            assert "device_ref" not in fetched.json()

            updated = client.patch(
                f"/api/v1/devices/by-key-hint/{hint}",
                headers=admin,
                json={"device_type": "esp32-cashier", "status": "active", "display_name": "Cashier Lobby"},
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["display_name"] == "Cashier Lobby"
            assert "device_id" not in updated.json()

            rotated = client.post(
                f"/api/v1/devices/by-key-hint/{hint}/rotate-key",
                headers=admin,
            )
            assert rotated.status_code == 200, rotated.text
            new_key = rotated.json()["device_key"]
            new_hint = rotated.json()["device_key_hint"]
            assert new_key and new_hint != hint
            assert "device_id" not in rotated.json()
            registered = client.post(
                "/api/v1/devices/register",
                json={"device_type": "esp32-cashier", "mac_address": "AA:BB:CC:DD:EE:71", "device_key": new_key},
            )
            assert registered.status_code == 200, registered.text
            assert client.post(
                "/api/v1/devices/heartbeat",
                headers={"X-M-Group-Device-Key": key},
                json={"device_type": "esp32-cashier", "status": "active"},
            ).status_code == 403
            assert client.post(
                "/api/v1/devices/heartbeat",
                headers={"X-M-Group-Device-Key": new_key},
                json={"device_type": "esp32-cashier", "status": "active"},
            ).status_code == 200
            assert client.get(f"/api/v1/devices/by-key-hint/{hint}", headers=admin).status_code == 404

            with client.app.state.db.connect() as conn:
                conn.execute("INSERT INTO identity_members(member_id,name) VALUES('nfc-member','NFC Test')")
                conn.commit()
            nfc_start = client.post(
                "/api/v1/members/nfc-member/nfc-registration/start",
                headers=admin,
                json={"cashier_key_hint": new_hint},
            )
            assert nfc_start.status_code == 200, nfc_start.text
            assert "device_id" not in nfc_start.json()
            assert "cashier_device_id" not in nfc_start.json()
            assert nfc_start.json()["cashier_location"] == "Cashier Lobby"

            dashboard = client.get("/api/v1/dashboard", headers=admin)
            assert dashboard.status_code == 200, dashboard.text
            for item in dashboard.json()["devices"] + dashboard.json()["payments"] + dashboard.json()["machines"]:
                assert "device_id" not in item
                assert "device_ref" not in item

            assert client.get(f"/api/v1/devices/{internal_id}", headers=admin).status_code == 404
            assert client.patch(
                f"/api/v1/devices/{internal_id}",
                headers=admin,
                json={"device_type": "esp32-cashier", "status": "active"},
            ).status_code == 404
            assert client.delete(f"/api/v1/devices/{internal_id}", headers=admin).status_code == 404
            assert client.post(
                f"/api/v1/devices/{internal_id}/provision",
                headers=admin,
                json={"device_type": "esp32-cashier", "display_name": "Legacy"},
            ).status_code == 404
            assert client.post(
                f"/api/v1/devices/{internal_id}/heartbeat",
                headers={"X-M-Group-Device-Key": key},
                json={"device_type": "esp32-cashier", "status": "active"},
            ).status_code == 404
        finally:
            main.get_settings = old
