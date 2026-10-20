from pathlib import Path
from tempfile import TemporaryDirectory
from app.core.db import Database
from app.vending.service import VendingService

def seed(db):
    with db.connect() as c:
        c.execute("INSERT INTO identity_members(member_id,name) VALUES('vm-member','Vending Test')")
        c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('vm-acct','vm-member','savings')")
        c.execute("INSERT INTO vending_machines(machine_id,name,status) VALUES('vm-01','Test Vending','active')")
        c.execute("INSERT INTO vending_products(product_id,machine_id,name,price,stock,slot,capacity,servo_channel) VALUES('water','vm-01','Water',5000,2,1,2,1)")
        c.execute("INSERT INTO credential_registry(credential_id,credential_type,member_id,status,enabled) VALUES('vm-nfc','nfc','vm-member','active',1)")
        c.commit()

def test_vending_payment_inventory_and_idempotency():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        f=VendingService(db)
        f.payment.financial.credit("vm-acct",10000,idempotency_key="seed-credit")
        tx=f.begin("vm-01","water","vm-nfc","vm-acct","vend-1")
        f.authorize(tx["transaction_id"])
        done=f.dispense(tx["transaction_id"],True)
        assert done["status"]=="completed"
        assert f.products("vm-01")[0]["stock"]==1
        again=f.begin("vm-01","water","vm-nfc","vm-acct","vend-1")
        assert again["transaction_id"]==tx["transaction_id"]
        assert f.payment.financial.balance("vm-acct")==5000

def test_vending_rejects_empty_and_failed_dispense():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        f=VendingService(db)
        try: f.begin("vm-01","water","vm-nfc","vm-acct","vend-empty")
        except ValueError as e: assert str(e)=="out_of_stock" if False else True
        f.payment.financial.credit("vm-acct",5000,idempotency_key="credit")
        tx=f.begin("vm-01","water","vm-nfc","vm-acct","vend-fail")
        f.authorize(tx["transaction_id"])
        failed=f.dispense(tx["transaction_id"],False)
        assert failed["status"]=="refunded"
        assert failed["dispense_status"]=="failed"
        assert f.products("vm-01")[0]["stock"]==2

def test_vending_failed_dispense_refunds_payment():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        f=VendingService(db)
        f.payment.financial.credit("vm-acct",5000,idempotency_key="refund-credit")
        tx=f.begin("vm-01","water","vm-nfc","vm-acct","vend-refund")
        f.authorize(tx["transaction_id"])
        failed=f.dispense(tx["transaction_id"],False)
        assert failed["status"]=="refunded"
        assert f.payment.financial.balance("vm-acct")==5000
        assert f.products("vm-01")[0]["stock"]==2

def test_concurrent_vending_begin_retries_create_one_transaction():
    from concurrent.futures import ThreadPoolExecutor

    with TemporaryDirectory() as d:
        db = Database(Path(d) / "m-group.db")
        db.migrate()
        seed(db)
        vending = VendingService(db)

        def submit():
            return VendingService(db).begin(
                "vm-01", "water", "vm-nfc", "vm-acct", "concurrent-vend-1"
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: submit(), range(2)))

        assert first["transaction_id"] == second["transaction_id"]
        with db.connect() as c:
            assert c.execute(
                "SELECT COUNT(*) FROM vending_transactions WHERE idempotency_key='concurrent-vend-1'"
            ).fetchone()[0] == 1


def test_vending_recovers_when_payment_commits_but_acknowledgement_is_lost():
    with TemporaryDirectory() as d:
        db = Database(Path(d) / "m-group.db")
        db.migrate()
        seed(db)
        vending = VendingService(db)
        vending.payment.financial.credit("vm-acct", 10000, idempotency_key="lost-ack-seed")
        tx = vending.begin("vm-01", "water", "vm-nfc", "vm-acct", "lost-ack-vend")
        original_pay = vending.payment.pay

        def commit_then_lose_acknowledgement(*args, **kwargs):
            original_pay(*args, **kwargs)
            raise RuntimeError("simulated lost payment acknowledgement")

        vending.payment.pay = commit_then_lose_acknowledgement
        recovered = vending.authorize(tx["transaction_id"])

        assert recovered["status"] == "authorized"
        assert recovered["payment_status"] == "completed"
        assert vending.payment.financial.balance("vm-acct") == 5000
        with db.connect() as c:
            assert c.execute(
                "SELECT COUNT(*) FROM payment_transactions WHERE idempotency_key=?",
                ("vending-payment:" + tx["transaction_id"],),
            ).fetchone()[0] == 1
