from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
import app.main as main
from app.core.db import Database
from app.vending.service import VendingService

from tests.auth_helpers import login_admin
def test_vending_registry_supports_many_machines_and_five_slots():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate()
        f=VendingService(db)
        for i in range(1,6):
            m=f.register(f"vm-{i}",f"Vending {i}",f"Location {i}",f"esp32-{i}")
            assert m["machine_id"]==f"vm-{i}"
        assert len(f.machines())==5
        assert [x["slot"] for x in f.slots("vm-3")]==[1,2,3,4,5]
        assert [x["product_id"] for x in f.slots("vm-3")] == ["1", "2", "3", "4", "5"]
        assert all(x["name"] is None for x in f.slots("vm-3"))

def test_vending_registry_isolates_machine_slots():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate()
        f=VendingService(db)
        f.register("a","A",hardware_id="dev-a")
        f.register("b","B",hardware_id="dev-b")
        f.upsert_product("a","water-a","Water A",5000,3,slot=1,capacity=5)
        f.upsert_product("b","water-b","Water B",6000,4,slot=1,capacity=5)
        assert f.products("a")[0]["price"]==5000
        assert f.products("b")[0]["price"]==6000
        assert f.slots("a")[0]["servo_channel"]==1
        assert f.slots("b")[0]["servo_channel"]==1

def test_vending_registry_rejects_duplicate_device_and_invalid_slot():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate()
        f=VendingService(db)
        f.register("a","A",hardware_id="same")
        try: f.register("b","B",hardware_id="same")
        except ValueError as e: assert str(e)=="device_already_registered"
        else: assert False
        try: f.upsert_product("a","p","P",1000,1,slot=6,capacity=1)
        except ValueError as e: assert str(e)=="slot_must_be_1_to_5"
        else: assert False

def test_vending_registry_api():
    with TemporaryDirectory() as d:
        old=main.get_settings
        main.get_settings=lambda:type("S",(),{"db_path":Path(d)/"m-group.db",})()
        try:
            client=TestClient(main.create_app())
            admin=login_admin(client)
            created=client.post("/api/v1/vending",headers=admin,json={
                "machine_id":"api-v1","name":"API Vending","location":"Lobby","hardware_id":"api-esp32"
            })
            assert created.status_code==200
            assert created.json()["status"]=="active"
            detail=client.get("/api/v1/vending/api-v1",headers=admin)
            assert detail.status_code==200
            assert len(detail.json()["slots"])==5
            product = client.put("/api/v1/vending/api-v1/products/1", headers=admin, json={
                "product_id":"1","name":"Water","price":1000,"stock":2,"capacity":5
            })
            assert product.status_code == 200, product.text
            assert product.json()["product_id"] == "1"
            assert product.json()["slot"] == product.json()["servo_channel"] == 1
            catalog = client.get("/api/v1/vending/api-v1/products", headers=admin)
            assert catalog.status_code == 200
            assert catalog.json()["products"][0]["product_id"] == "1"
            second = client.post("/api/v1/vending", headers=admin, json={
                "machine_id":"api-v2","name":"API Vending 2","location":"Back"
            })
            assert second.status_code == 200
            second_product = client.put("/api/v1/vending/api-v2/products/1", headers=admin, json={
                "product_id":"1","name":"Juice","price":1500,"stock":1,"capacity":3
            })
            assert second_product.status_code == 200, second_product.text
            assert client.get("/api/v1/vending/api-v2/products", headers=admin).json()["products"][0]["product_id"] == "1"
            invalid = client.put("/api/v1/vending/api-v1/products/water", headers=admin, json={
                "product_id":"water","name":"Legacy ID","price":1000,"stock":1,"capacity":1
            })
            assert invalid.status_code == 400
            updated=client.patch("/api/v1/vending/api-v1",headers=admin,json={"location":"Gate"})
            assert updated.status_code==200
            assert updated.json()["location"]=="Gate"
            assert client.post("/api/v1/vending/api-v1/disable",headers=admin).status_code==200
            assert client.post("/api/v1/vending/api-v1/enable",headers=admin).json()["status"]=="active"
        finally:
            main.get_settings=old
