from pathlib import Path
from tempfile import TemporaryDirectory
from app.core.db import Database
from app.payment.service import PaymentService

def seed(db):
    with db.connect() as c:
        c.execute("INSERT INTO identity_members(member_id,name) VALUES('member-1','Test')")
        c.execute("INSERT INTO identity_credentials(credential_id,member_id,credential_type) VALUES('cred-1','member-1','nfc')")
        c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('acct-1','member-1','savings')")
        c.execute("INSERT INTO financial_ledger(account_id,direction,amount,reference) VALUES('acct-1','credit',100000,'seed')")
        c.commit()

def test_nfc_payment_idempotency():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        p=PaymentService(db)
        a=p.pay("cred-1","acct-1",25000,method="NFC",idempotency_key="idem-1")
        b=p.pay("cred-1","acct-1",25000,method="NFC",idempotency_key="idem-1")
        assert a["transaction_id"] == b["transaction_id"]
        with db.connect() as c:
            balance=c.execute("SELECT COALESCE(SUM(CASE WHEN direction='credit' THEN amount ELSE -amount END),0) FROM financial_ledger WHERE account_id='acct-1'").fetchone()[0]
        assert balance == 75000

def test_qris_is_a_supported_future_method():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        result=PaymentService(db).pay("cred-1","acct-1",1000,method="QRIS",provider="future-qris",idempotency_key="q-1")
        assert result["method"] == "QRIS"
        assert result["provider"] == "future-qris"

def test_payment_uses_financial_core_and_rejects_account_mismatch():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        with db.connect() as c:
            c.execute("INSERT INTO identity_members(member_id,name) VALUES('member-2','Other')")
            c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('acct-2','member-2','savings')")
            c.execute("INSERT INTO financial_ledger(account_id,direction,amount,reference) VALUES('acct-2','credit',50000,'seed')")
            c.commit()
        p=PaymentService(db)
        try:
            p.pay("cred-1","acct-2",1000,method="NFC")
            assert False
        except PermissionError as e:
            assert str(e) == "credential_account_mismatch"
        with db.connect() as c:
            assert c.execute("SELECT COUNT(*) FROM payment_transactions").fetchone()[0] == 0
            assert c.execute("SELECT COUNT(*) FROM financial_transactions").fetchone()[0] == 0

def test_payment_insufficient_balance_is_atomic():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        try:
            PaymentService(db).pay("cred-1","acct-1",100001,method="NFC",idempotency_key="too-much")
            assert False
        except ValueError as e:
            assert str(e) == "insufficient_balance"
        with db.connect() as c:
            assert c.execute("SELECT COUNT(*) FROM payment_transactions").fetchone()[0] == 0
            assert c.execute("SELECT COUNT(*) FROM financial_transactions").fetchone()[0] == 0
            assert c.execute("SELECT COALESCE(SUM(CASE WHEN direction='credit' THEN amount ELSE -amount END),0) FROM financial_ledger WHERE account_id='acct-1'").fetchone()[0] == 100000


def test_nfc_payment_resolves_savings_account_from_credential():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        result=PaymentService(db).pay(
            "cred-1", None, 25000, method="NFC",
            idempotency_key="resolve-1"
        )
        assert result["final_amount"] == 25000
        assert result["balance_before"] == 100000
        assert result["balance_after"] == 75000


def test_nfc_payment_rejects_idempotency_key_reuse_with_different_request():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        p=PaymentService(db)
        p.pay("cred-1","acct-1",10000,method="NFC",idempotency_key="idem-conflict")
        try:
            p.pay("cred-1","acct-1",11000,method="NFC",idempotency_key="idem-conflict")
            assert False
        except ValueError as e:
            assert str(e) == "idempotency_key_conflict"


def test_nfc_payment_records_100_percent_promo_without_ledger_debit():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        result=PaymentService(db).pay(
            "cred-1","acct-1",0,method="NFC",original_amount=5000,
            discount_amount=5000,promo_id="promo-100",
            idempotency_key="promo-100"
        )
        assert result["original_amount"] == 5000
        assert result["discount_amount"] == 5000
        assert result["final_amount"] == 0
        assert result["ledger_reference"] is None
        assert result["balance_before"] == 100000
        assert result["balance_after"] == 100000
