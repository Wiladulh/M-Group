from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from app.core.db import Database
from app.vending.service import VendingService

def seed(db):
    with db.connect() as c:
        c.execute("INSERT INTO identity_members(member_id,name) VALUES('pm-member','Payment Method Test')")
        c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('pm-acct','pm-member','savings')")
        c.execute("INSERT INTO vending_machines(machine_id,name,status) VALUES('pm-01','Payment Method Vending','active')")
        c.execute("INSERT INTO vending_products(product_id,machine_id,name,price,stock) VALUES('water','pm-01','Water',5000,2)")
        c.execute("INSERT INTO credential_registry(credential_id,credential_type,member_id,status,enabled) VALUES('pm-nfc','nfc','pm-member','active',1)")
        c.commit()

def test_vending_transaction_binds_payment_method_and_provider():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        f=VendingService(db)
        f.payment.financial.credit("pm-acct",10000,idempotency_key="pm-credit")
        tx=f.begin("pm-01","water","pm-nfc","pm-acct","pm-nfc-1","NFC","local")
        assert tx["payment_method"]=="NFC"
        assert tx["payment_provider"]=="local"
        assert tx["base_amount"]==5000
        assert tx["discount_amount"]==0
        assert tx["amount"]==5000
        assert tx["payment_status"]=="pending"
        done=f.dispense(f.authorize(tx["transaction_id"])["transaction_id"],True)
        assert done["payment_status"]=="completed"

def test_vending_qris_is_stored_separately_but_not_activated():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        f=VendingService(db)
        tx=f.begin("pm-01","water","pm-nfc","pm-acct","pm-qris-1","QRIS","provider-x")
        assert tx["payment_method"]=="QRIS"
        assert tx["payment_provider"]=="provider-x"
        with pytest.raises(ValueError, match="qris_payment_provider_not_activated"):
            f.authorize(tx["transaction_id"])
        failed=f.get(tx["transaction_id"])
        assert failed["payment_status"]=="failed"
        assert failed["status"]=="failed"

def test_vending_rejects_invalid_method_provider_pair():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        f=VendingService(db)
        with pytest.raises(ValueError, match="invalid_nfc_provider"):
            f.begin("pm-01","water","pm-nfc","pm-acct","pm-invalid-1","NFC","provider-x")


def test_vending_promo_foundation_is_scoped_by_machine_product_and_method():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        with db.connect() as c:
            c.execute("""INSERT INTO vending_promo_rules
                (promo_id,machine_id,product_id,payment_method,payment_provider,discount_percent,starts_at,ends_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                ("promo-nfc","pm-01","water","NFC","local",10,"2026-10-01T00:00:00","2026-10-31T23:59:59"))
            c.execute("""INSERT INTO vending_promo_rules
                (promo_id,machine_id,product_id,payment_method,payment_provider,discount_percent)
                VALUES(?,?,?,?,?,?)""",
                ("promo-qris","pm-01","water","QRIS","provider-x",20))
            rows=c.execute("""SELECT promo_id,machine_id,product_id,payment_method,payment_provider,discount_percent
                FROM vending_promo_rules WHERE machine_id=? ORDER BY promo_id""",("pm-01",)).fetchall()
        assert [dict(r) for r in rows]==[
            {"promo_id":"promo-nfc","machine_id":"pm-01","product_id":"water","payment_method":"NFC","payment_provider":"local","discount_percent":10},
            {"promo_id":"promo-qris","machine_id":"pm-01","product_id":"water","payment_method":"QRIS","payment_provider":"provider-x","discount_percent":20},
        ]
        # Promotion rules may be stored for future use, but the feature is
        # intentionally inactive until launch: transactions must charge base price.
        f=VendingService(db)
        tx=f.begin("pm-01","water","pm-nfc","pm-acct","pm-promo-disabled","NFC","local")
        assert tx["base_amount"]==5000
        assert tx["discount_amount"]==0
        assert tx["amount"]==5000
        assert tx["promo_id"] is None
