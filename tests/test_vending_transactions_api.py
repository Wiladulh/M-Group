from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import app.main as main
from app.vending.service import VendingService


from conftest import login_admin
def test_admin_can_read_vending_transactions_for_selected_machine():
    with TemporaryDirectory() as tmp:
        old = main.get_settings
        main.get_settings = lambda: type(
            "S", (), {"db_path": Path(tmp) / "m-group.db",}
        )()
        try:
            client = TestClient(main.create_app())
            db = client.app.state.db
            with db.connect() as c:
                c.execute("INSERT INTO identity_members(member_id,name) VALUES('vm-member','Vending Test')")
                c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('vm-acct','vm-member','savings')")
                c.execute("INSERT INTO vending_machines(machine_id,name,status) VALUES('vm-01','Test Vending','active')")
                c.execute("INSERT INTO vending_products(product_id,machine_id,name,price,stock,slot,capacity,servo_channel) VALUES('water','vm-01','Water',5000,2,1,2,1)")
                c.execute("INSERT INTO credential_registry(credential_id,credential_type,member_id,status,enabled) VALUES('vm-nfc','nfc','vm-member','active',1)")
                c.commit()
            service = VendingService(db)
            service.payment.financial.credit("vm-acct", 5000, idempotency_key="history-seed")
            tx = service.begin("vm-01", "water", "vm-nfc", "vm-acct", "history-tx")
            service.authorize(tx["transaction_id"])
            service.dispense(tx["transaction_id"], True)

            response = client.get(
                "/api/v1/vending/vm-01/transactions",
                headers=login_admin(client),
            )
            assert response.status_code == 200
            rows = response.json()["transactions"]
            assert len(rows) == 1
            assert rows[0]["transaction_id"] == tx["transaction_id"]
            assert rows[0]["product_id"] == "1"
            assert rows[0]["status"] == "completed"
            assert rows[0]["dispense_status"] == "success"
        finally:
            main.get_settings = old
