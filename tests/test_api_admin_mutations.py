from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
import app.main as main


from conftest import login_admin
def test_financial_and_vending_mutations_require_admin_token():
    with TemporaryDirectory() as directory:
        old = main.get_settings
        main.get_settings = lambda: type(
            "S", (), {"db_path": Path(directory) / "m-group.db",}
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
