from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.db import Database
from app.financial.service import FinancialService


def test_topup_correction_is_ledger_backed_and_idempotent():
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "nvm.db")
        db.migrate()
        with db.connect() as c:
            c.execute("INSERT INTO identity_members(member_id,name) VALUES('NTR-00001','Test Member')")
            c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('NTR-00001','NTR-00001','savings')")
            c.commit()
        financial = FinancialService(db)
        original = financial.credit("NTR-00001", 10000, reference="topup", idempotency_key="topup-test-1")
        corrected = financial.correct_credit(
            "NTR-00001", original["transaction_id"], 7000,
            "Input nominal salah", "correct-test-0001", "operator-test"
        )
        assert corrected["original_amount"] == 10000
        assert corrected["corrected_amount"] == 7000
        assert corrected["adjustment_amount"] == -3000
        assert financial.balance("NTR-00001") == 7000
        replay = financial.correct_credit(
            "NTR-00001", original["transaction_id"], 7000,
            "Input nominal salah", "correct-test-0001", "operator-test"
        )
        assert replay["correction_id"] == corrected["correction_id"]
        assert replay["replayed"] is True
        with db.connect() as c:
            assert c.execute("SELECT COUNT(*) FROM financial_corrections").fetchone()[0] == 1
            assert c.execute("SELECT COUNT(*) FROM financial_ledger WHERE account_id='NTR-00001'").fetchone()[0] == 2


def test_topup_correction_rejects_duplicate_and_invalid_amount():
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "nvm.db")
        db.migrate()
        with db.connect() as c:
            c.execute("INSERT INTO identity_members(member_id,name) VALUES('NTR-00002','Test Member')")
            c.execute("INSERT INTO financial_accounts(account_id,member_id,account_type) VALUES('NTR-00002','NTR-00002','savings')")
            c.commit()
        financial = FinancialService(db)
        original = financial.credit("NTR-00002", 5000, idempotency_key="topup-test-2")
        financial.correct_credit("NTR-00002", original["transaction_id"], 4000, "Koreksi valid", "correct-test-0002", "operator-test")
        try:
            financial.correct_credit("NTR-00002", original["transaction_id"], 3000, "Koreksi ulang", "correct-test-0003", "operator-test")
            assert False, "second correction must be rejected"
        except ValueError as exc:
            assert str(exc) == "original_transaction_already_corrected"
        try:
            financial.correct_credit("NTR-00002", "missing", 0, "Invalid", "correct-test-0004", "operator-test")
            assert False, "invalid amount must be rejected"
        except ValueError as exc:
            assert str(exc) == "corrected_amount_must_be_positive_integer"
