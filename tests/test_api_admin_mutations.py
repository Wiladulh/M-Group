from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
import app.main as main


from tests.auth_helpers import login_admin
def test_financial_and_vending_mutations_require_admin_session():
    with TemporaryDirectory() as directory:
        old = main.get_settings
        main.get_settings = lambda: type(
            "S", (), {"db_path": Path(directory) / "m-group.db"}
        )()
        try:
            client = TestClient(main.create_app())
            with client.app.state.db.connect() as conn:
                conn.execute("INSERT INTO identity_members(member_id,name) VALUES('member-1','Test')")
                conn.execute(
                    "INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('account-1','member-1','savings')"
                )
                conn.execute("INSERT INTO vending_machines(machine_id,name) VALUES('machine-1','Test machine')")
                conn.commit()

            assert client.post(
                "/api/v1/accounts/account-1/credit", json={"amount": 100, "reference": "test"}
            ).status_code == 401
            assert client.post(
                "/api/v1/accounts/account-1/debit", json={"amount": 100, "reference": "test"}
            ).status_code == 401
            assert client.post(
                "/api/v1/vending", json={"machine_id": "machine-2", "name": "Test"}
            ).status_code == 401
            assert client.put(
                "/api/v1/vending/machine-1/products/1",
                json={
                    "product_id": "1", "name": "Water", "price": 100,
                    "stock": 1, "slot": 1, "capacity": 1, "servo_channel": 1,
                },
            ).status_code == 401

            admin = login_admin(client)
            credit = client.post(
                "/api/v1/accounts/account-1/credit",
                headers=admin,
                json={"amount": 100, "reference": "test", "idempotency_key": "admin-credit-1"},
            )
            assert credit.status_code == 200, credit.text
            product = client.put(
                "/api/v1/vending/machine-1/products/1",
                headers=admin,
                json={
                    "product_id": "1", "name": "Water", "price": 100,
                    "stock": 1, "slot": 1, "capacity": 1, "servo_channel": 1,
                },
            )
            assert product.status_code == 200, product.text
        finally:
            main.get_settings = old


def test_vending_product_image_upload_serve_and_delete():
    from io import BytesIO
    from PIL import Image

    with TemporaryDirectory() as directory:
        old = main.get_settings
        main.get_settings = lambda: type(
            "S", (), {"db_path": Path(directory) / "m-group.db"}
        )()
        try:
            client = TestClient(main.create_app())
            with client.app.state.db.connect() as conn:
                conn.execute("INSERT INTO vending_machines(machine_id,name) VALUES('machine-image','Image test')")
                conn.commit()
            admin = login_admin(client)
            product = client.put(
                "/api/v1/vending/machine-image/products/1",
                headers=admin,
                json={
                    "product_id": "1", "name": "Water", "price": 5000,
                    "stock": 2, "slot": 1, "capacity": 5, "servo_channel": 1,
                },
            )
            assert product.status_code == 200, product.text

            buffer = BytesIO()
            Image.new("RGB", (2, 2), (20, 80, 120)).save(buffer, format="PNG")
            image_bytes = buffer.getvalue()
            uploaded = client.put(
                "/api/v1/vending/machine-image/products/1/image",
                headers=admin,
                files={"image": ("water.png", image_bytes, "image/png")},
            )
            assert uploaded.status_code == 200, uploaded.text
            assert uploaded.json()["mime_type"] == "image/png"
            assert uploaded.json()["size_bytes"] == len(image_bytes)

            catalog = client.get("/api/v1/vending/machine-image/products", headers=admin)
            assert catalog.status_code == 200, catalog.text
            item = catalog.json()["products"][0]
            assert item["image_url"] == "/api/v1/vending/machine-image/products/1/image"

            fetched = client.get(item["image_url"], headers=admin)
            assert fetched.status_code == 200
            assert fetched.headers["content-type"].startswith("image/png")
            assert fetched.content == image_bytes

            deleted = client.delete(
                "/api/v1/vending/machine-image/products/1/image", headers=admin
            )
            assert deleted.status_code == 200, deleted.text
            catalog_after = client.get("/api/v1/vending/machine-image/products", headers=admin)
            assert catalog_after.json()["products"][0]["image_url"] is None
        finally:
            main.get_settings = old


def test_vending_product_image_rejects_oversize_and_invalid_images():
    with TemporaryDirectory() as directory:
        old = main.get_settings
        main.get_settings = lambda: type(
            "S", (), {"db_path": Path(directory) / "m-group.db"}
        )()
        try:
            client = TestClient(main.create_app())
            with client.app.state.db.connect() as conn:
                conn.execute("INSERT INTO vending_machines(machine_id,name) VALUES('machine-image','Image test')")
                conn.commit()
            admin = login_admin(client)
            product = client.put(
                "/api/v1/vending/machine-image/products/1",
                headers=admin,
                json={
                    "product_id": "1", "name": "Water", "price": 5000,
                    "stock": 2, "slot": 1, "capacity": 5, "servo_channel": 1,
                },
            )
            assert product.status_code == 200, product.text

            oversize = client.put(
                "/api/v1/vending/machine-image/products/1/image",
                headers=admin,
                files={"image": ("large.png", b"x" * (2 * 1024 * 1024 + 1), "image/png")},
            )
            assert oversize.status_code == 413
            invalid = client.put(
                "/api/v1/vending/machine-image/products/1/image",
                headers=admin,
                files={"image": ("not-image.png", b"not an image", "image/png")},
            )
            assert invalid.status_code == 415
        finally:
            main.get_settings = old


def test_vending_product_image_can_be_fetched_with_device_key():
    from io import BytesIO
    from PIL import Image

    with TemporaryDirectory() as directory:
        old = main.get_settings
        main.get_settings = lambda: type(
            "S", (), {"db_path": Path(directory) / "m-group.db"}
        )()
        try:
            client = TestClient(main.create_app())
            admin = login_admin(client)
            provision = client.post(
                "/api/v1/devices/provision",
                headers=admin,
                json={"device_type": "esp32-s3-vending", "display_name": "Vending image test"},
            )
            assert provision.status_code == 200, provision.text
            key = provision.json()["device_key"]
            registration = client.post(
                "/api/v1/devices/register",
                json={
                    "device_type": "esp32-s3-vending",
                    "mac_address": "AA:BB:CC:00:48:02",
                    "device_key": key,
                },
            )
            assert registration.status_code == 200, registration.text
            heartbeat = client.post(
                "/api/v1/devices/heartbeat",
                headers={"X-M-Group-Device-Key": key},
                json={"device_type": "esp32-s3-vending", "status": "active"},
            )
            assert heartbeat.status_code == 200, heartbeat.text

            with client.app.state.db.connect() as conn:
                device_row = conn.execute(
                    "SELECT device_id FROM device_registry WHERE auth_key_hash=?",
                    (__import__("hashlib").sha256(key.encode("utf-8")).hexdigest(),),
                ).fetchone()
                assert device_row is not None
                machine_row = conn.execute(
                    "SELECT machine_id FROM vending_machines WHERE device_id=?",
                    (device_row["device_id"],),
                ).fetchone()
                assert machine_row is not None
                machine_id = machine_row["machine_id"]
            product = client.put(
                f"/api/v1/vending/{machine_id}/products/1",
                headers=admin,
                json={
                    "product_id": "1", "name": "Water", "price": 5000,
                    "stock": 2, "slot": 1, "capacity": 5, "servo_channel": 1,
                },
            )
            assert product.status_code == 200, product.text

            buffer = BytesIO()
            Image.new("RGB", (2, 2), (20, 80, 120)).save(buffer, format="JPEG")
            image_bytes = buffer.getvalue()
            uploaded = client.put(
                f"/api/v1/vending/{machine_id}/products/1/image",
                headers=admin,
                files={"image": ("water.jpg", image_bytes, "image/jpeg")},
            )
            assert uploaded.status_code == 200, uploaded.text

            device_headers = {"X-M-Group-Device-Key": key}
            catalog = client.get(f"/api/v1/vending/{machine_id}/products", headers=device_headers)
            assert catalog.status_code == 200, catalog.text
            image = client.get(catalog.json()["products"][0]["image_url"], headers=device_headers)
            assert image.status_code == 200
            assert image.headers["content-type"].startswith("image/jpeg")
            assert image.content == image_bytes

            other = client.post(
                "/api/v1/devices/provision",
                headers=admin,
                json={"device_type": "esp32-s3-vending", "display_name": "Other Vending"},
            )
            assert other.status_code == 200, other.text
            other_headers = {"X-M-Group-Device-Key": other.json()["device_key"]}
            assert client.get(
                f"/api/v1/vending/{machine_id}/products", headers=other_headers
            ).status_code == 403
            assert client.get(
                f"/api/v1/vending/{machine_id}/products/1/image", headers=other_headers
            ).status_code == 403
        finally:
            main.get_settings = old
