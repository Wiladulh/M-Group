from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
import app.main as main


from tests.auth_helpers import login_admin
def test_dashboard_provisioning_key_activates_firmware_heartbeat_for_both_device_types():
    with TemporaryDirectory() as tmp:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {"db_path": Path(tmp) / "m-group.db",})()
        try:
            client = TestClient(main.create_app())
            for device_type in ("esp32-cashier", "esp32-s3-vending"):
                provision = client.post("/api/v1/devices/provision", json={"device_type": device_type, "display_name": "Test unit"}, headers=login_admin(client))
                assert provision.status_code == 200
                key = provision.json()["device_key"]
                assert key and len(key) >= 32
                assert client.post("/api/v1/devices/heartbeat", json={"device_type": device_type}).status_code == 401
                heartbeat = client.post("/api/v1/devices/heartbeat", json={"device_type": device_type, "status": "active"}, headers={"X-M-Group-Device-Key": key})
                assert heartbeat.status_code == 200
                assert heartbeat.json()["status"] == "active"
                assert client.post("/api/v1/devices/heartbeat", json={"device_type": device_type}, headers={"X-M-Group-Device-Key": "wrong-key"}).status_code == 403
        finally:
            main.get_settings = old


def test_both_firmware_targets_use_existing_provisioning_contract():
    root = Path(__file__).resolve().parents[1]
    cashier = (root / "esp32/cashier/MGroupCashier.ino").read_text()
    vending = (root / "esp32/vending/MGroupVending.ino").read_text()
    portal = (root / "esp32/common/MGroupConfigPortal.h").read_text()
    for source in (cashier, vending):
        assert '#include "MGroupConfigPortal.h"' in source
        assert '"/api/v1/devices/heartbeat"' in source and '"/api/v1/vending/self/products"' in source
        assert "X-M-Group-Device-Key" in source
    assert 'server_.on("/",HTTP_GET' in portal and 'server_.on("/save",HTTP_POST' in portal
    assert 'prefs_.putString("device_key",deviceKey)' in portal
    assert 'prefs_.getString("device_key",*key_)' in portal
