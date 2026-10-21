from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient

import app.main as main


from tests.auth_helpers import login_admin
def test_device_heartbeat_and_vending_product_sync():
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {"db_path": Path(d) / "m-group.db",})()
        try:
            client = TestClient(main.create_app())

            cashier = client.post(
                "/api/v1/devices/provision",
                json={"device_type": "esp32-cashier", "display_name": "Cashier 01"},
                headers=login_admin(client),
            )
            assert cashier.status_code == 200
            cashier_key = cashier.json()["device_key"]

            vending = client.post(
                "/api/v1/devices/provision",
                json={"device_type": "esp32-s3-vending", "display_name": "Vending 01"},
                headers=login_admin(client),
            )
            assert vending.status_code == 200
            vending_key = vending.json()["device_key"]

            hb = client.post(
                "/api/v1/devices/heartbeat",
                json={"device_type": "esp32-cashier", "status": "active"},
                headers={"X-M-Group-Device-Key": cashier_key},
            )
            assert hb.status_code == 200

            vm = client.post(
                "/api/v1/devices/heartbeat",
                json={"device_type": "esp32-s3-vending", "status": "active"},
                headers={"X-M-Group-Device-Key": vending_key},
            )
            assert vm.status_code == 200

            with client.app.state.db.connect() as c:
                vending_internal = c.execute(
                    "SELECT device_id FROM device_registry WHERE auth_key_hash=?",
                    (__import__("hashlib").sha256(vending_key.encode()).hexdigest(),),
                ).fetchone()
                assert vending_internal is not None
                c.execute(
                    "INSERT INTO vending_machines(machine_id,name,status,device_id) "
                    "VALUES('vm-01','Vending 01','active',?)",
                    (vending_internal["device_id"],),
                )
                c.commit()

            product = client.put(
                "/api/v1/vending/vm-01/products/1",
                headers=login_admin(client),
                json={
                    "product_id": "1",
                    "name": "Air Mineral",
                    "price": 3000,
                    "stock": 12,
                    "enabled": True,
                },
            )
            assert product.status_code == 200
            assert product.json()["stock"] == 12

            sync = client.get("/api/v1/vending/vm-01/products", headers={"X-M-Group-Device-Key": vending_key})
            assert sync.status_code == 200
            assert sync.json()["machine"]["machine_id"] == "vm-01"
            assert sync.json()["products"][0]["product_id"] == "1"

            dashboard = client.get("/api/v1/dashboard", headers=login_admin(client))
            assert dashboard.status_code == 200
            devices = {x["display_name"]: x for x in dashboard.json()["devices"]}
            assert devices["Cashier 01"]["status"] == "active"
            assert devices["Vending 01"]["device_type"] == "esp32-s3-vending"
            assert all("device_id" not in x and "device_ref" not in x for x in dashboard.json()["devices"])
        finally:
            main.get_settings = old
