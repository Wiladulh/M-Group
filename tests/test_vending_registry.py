from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
import app.main as main
from app.core.db import Database
from app.vending.service import VendingService

def test_vending_registry_supports_many_machines_and_five_slots():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate()
        f=VendingService(db)
        for i in range(1,6):
            m=f.register(f"vm-{i}",f"Vending {i}",f"Location {i}",f"esp32-{i}")
            assert m["machine_id"]==f"vm-{i}"
        assert len(f.machines())==5
        assert [x["slot"] for x in f.slots("vm-3")]==[1,2,3,4,5]
        assert all(x["product_id"] is None for x in f.slots("vm-3"))

def test_vending_registry_isolates_machine_slots():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate()
        f=VendingService(db)
        f.register("a","A",device_id="dev-a")
        f.register("b","B",device_id="dev-b")
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
        f.register("a","A",device_id="same")
        try: f.register("b","B",device_id="same")
        except ValueError as e: assert str(e)=="device_already_registered"
        else: assert False
        try: f.upsert_product("a","p","P",1000,1,slot=6,capacity=1)
        except ValueError as e: assert str(e)=="slot_must_be_1_to_5"
        else: assert False

def test_vending_registry_api():
    with TemporaryDirectory() as d:
        old=main.get_settings
        main.get_settings=lambda:type("S",(),{"db_path":Path(d)/"m-group.db"})()
        try:
            client=TestClient(main.create_app())
            created=client.post("/api/v1/vending",json={
                "machine_id":"api-v1","name":"API Vending","location":"Lobby","device_id":"api-esp32"
            })
            assert created.status_code==200
            assert created.json()["status"]=="active"
            detail=client.get("/api/v1/vending/api-v1")
            assert detail.status_code==200
            assert len(detail.json()["slots"])==5
            updated=client.patch("/api/v1/vending/api-v1",json={"location":"Gate"})
            assert updated.status_code==200
            assert updated.json()["location"]=="Gate"
            assert client.post("/api/v1/vending/api-v1/disable").status_code==200
            assert client.post("/api/v1/vending/api-v1/enable").json()["status"]=="active"
        finally:
            main.get_settings=old
