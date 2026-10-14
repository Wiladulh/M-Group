from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
import app.main as main

def test_dashboard_exposes_financial_payment_and_vending_data():
    with TemporaryDirectory() as d:
        old = main.get_settings
        main.get_settings = lambda: type("S", (), {"db_path": Path(d) / "m-group.db", "admin_token": "admin-secret"})()
        try:
            client = TestClient(main.create_app())
            with client.app.state.db.connect() as c:
                c.execute("INSERT INTO identity_members(member_id,name) VALUES('m1','Member')")
                c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('a1','m1','savings')")
                c.execute("INSERT INTO financial_ledger(account_id,direction,amount,reference) VALUES('a1','credit',50000,'seed')")
                c.execute("INSERT INTO vending_machines(machine_id,name) VALUES('v1','Vending 1')")
                c.commit()
            denied = client.get("/api/v1/dashboard")
            assert denied.status_code == 401
            r = client.get("/api/v1/dashboard", headers={"X-M-Group-Admin-Token": "admin-secret"})
            assert r.status_code == 200
            data = r.json()
            assert data["members"][0]["member_id"] == "m1"
            assert data["accounts"][0]["balance"] == 50000
            assert data["machines"][0]["machine_id"] == "v1"
            admin = {"X-M-Group-Admin-Token": "admin-secret"}
            for path in (
                "/api/v1/audit",
                "/api/v1/devices/private-device/events",
                "/api/v1/accounts/a1/balance",
                "/api/v1/accounts/a1/ledger",
                "/api/v1/credentials/private-credential/account",
                "/api/v1/access/private-credential",
                "/api/v1/vending",
                "/api/v1/vending/v1",
                "/api/v1/vending/v1/products",
            ):
                assert client.get(path).status_code == 401, path
            assert client.get("/api/v1/audit", headers=admin).status_code == 200
            assert client.get("/api/v1/accounts/a1/balance", headers=admin).json()["balance"] == 50000
            assert client.get("/api/v1/accounts/a1/ledger", headers=admin).status_code == 200
            assert client.get("/api/v1/vending", headers=admin).status_code == 200
            assert client.get("/api/v1/vending/v1/products", headers=admin).status_code == 200
            assert client.get("/").status_code == 200
        finally:
            main.get_settings = old
