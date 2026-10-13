from pathlib import Path
from tempfile import TemporaryDirectory
from app.core.db import Database
from app.financial.service import FinancialService

def seed(db):
    with db.connect() as c:
        c.execute("INSERT INTO identity_members(member_id,name) VALUES('member-fin-1','Financial Test')")
        c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('acct-fin-1','member-fin-1','savings')")
        c.commit()

def test_credit_debit_balance_and_ledger():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        f=FinancialService(db)
        a=f.credit("acct-fin-1",100000,reference="deposit",idempotency_key="dep-1")
        assert a["transaction_type"] == "credit"
        assert f.balance("acct-fin-1") == 100000
        b=f.debit("acct-fin-1",25000,reference="withdrawal",idempotency_key="wd-1")
        assert b["transaction_type"] == "debit"
        assert f.balance("acct-fin-1") == 75000
        assert len(f.ledger("acct-fin-1")) == 2

def test_financial_idempotency_and_insufficient_balance():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db"); db.migrate(); seed(db)
        f=FinancialService(db)
        a=f.credit("acct-fin-1",50000,idempotency_key="same")
        b=f.credit("acct-fin-1",50000,idempotency_key="same")
        assert a["transaction_id"] == b["transaction_id"]
        assert f.balance("acct-fin-1") == 50000
        try:
            f.debit("acct-fin-1",50001)
            assert False
        except ValueError as e:
            assert str(e) == "insufficient_balance"

# Financial core CI trigger: run against the complete main tree.
