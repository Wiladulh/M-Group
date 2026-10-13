from uuid import uuid4

from app.identity.service import IdentityService
from app.financial.service import FinancialService


class PaymentService:
    def __init__(self, db):
        self.db = db
        self.identity = IdentityService(db)
        self.financial = FinancialService(db)

    def pay(
        self,
        credential_id,
        account_id=None,
        amount=None,
        reference=None,
        method="NFC",
        provider="local",
        idempotency_key=None,
        device_id=None,
        pin=None,
        original_amount=None,
        discount_amount=0,
        promo_id=None,
    ):
        if method not in {"NFC", "QRIS", "CASH"}:
            raise ValueError("unsupported_payment_method")
        if method == "NFC" and provider != "local":
            raise ValueError("invalid_nfc_provider")
        if not isinstance(discount_amount, int) or isinstance(discount_amount, bool) or discount_amount < 0:
            raise ValueError("discount_amount_must_be_nonnegative_integer")

        if original_amount is None:
            original_amount = amount
        if not isinstance(original_amount, int) or isinstance(original_amount, bool) or original_amount <= 0:
            raise ValueError("original_amount_must_be_positive_integer")

        if amount is None:
            amount = original_amount - discount_amount
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            raise ValueError("amount_must_be_nonnegative_integer")
        if discount_amount > original_amount or amount != original_amount - discount_amount:
            raise ValueError("invalid_payment_amounts")

        auth = self.identity.authorize_credential(credential_id)
        if not auth["authorized"]:
            raise PermissionError(auth["reason"])

        resolved = self.identity.account_for_credential(credential_id)
        if not resolved["authorized"]:
            raise PermissionError(resolved["reason"])
        resolved_account_id = resolved["account_id"]
        if account_id is not None and account_id != resolved_account_id:
            raise PermissionError("credential_account_mismatch")
        account_id = resolved_account_id

        if method == "NFC" and device_id is not None:
            if pin is None:
                raise PermissionError("pin_required")
            if not self.identity.verify_credential_pin(credential_id, pin):
                raise PermissionError("invalid_pin")

        with self.db.connect() as c:
            if idempotency_key:
                row = c.execute(
                    "SELECT transaction_id,status,original_amount,discount_amount,final_amount,"
                    "method,provider,account_id,balance_before,balance_after,promo_id "
                    "FROM payment_transactions WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if row:
                    if (
                        row["account_id"] != account_id
                        or row["method"] != method
                        or row["provider"] != provider
                        or row["original_amount"] != original_amount
                        or row["discount_amount"] != discount_amount
                    ):
                        raise ValueError("idempotency_key_conflict")
                    return {
                        "transaction_id": row["transaction_id"],
                        "status": row["status"],
                        "original_amount": row["original_amount"],
                        "discount_amount": row["discount_amount"],
                        "final_amount": row["final_amount"],
                        "method": row["method"],
                        "provider": row["provider"],
                        "device_id": device_id,
                        "promo_id": row["promo_id"],
                        "balance": row["balance_after"],
                    }

            tx = reference or "pay-" + uuid4().hex
            balance_before = self._balance_on_connection(c, account_id)

            if amount > 0:
                if balance_before < amount:
                    raise ValueError("insufficient_balance")
                financial_tx = self.financial.debit_on_connection(
                    c,
                    account_id,
                    amount,
                    reference=tx,
                    idempotency_key="payment:" + tx,
                )
                ledger_reference = financial_tx["transaction_id"]
            else:
                ledger_reference = None

            balance_after = self._balance_on_connection(c, account_id)

            c.execute(
                "INSERT INTO payment_transactions "
                "(transaction_id,credential_id,account_id,amount,status,method,provider,"
                "idempotency_key,device_id,original_amount,discount_amount,final_amount,"
                "promo_id,balance_before,balance_after) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    tx,
                    credential_id,
                    account_id,
                    amount,
                    "completed",
                    method,
                    provider,
                    idempotency_key,
                    device_id,
                    original_amount,
                    discount_amount,
                    amount,
                    promo_id,
                    balance_before,
                    balance_after,
                ),
            )
            c.execute(
                "INSERT INTO audit_events(event_type,entity_type,entity_id,detail) "
                "VALUES(?,?,?,?)",
                (
                    "payment",
                    "payment_transaction",
                    tx,
                    f"completed:{method}:{provider}:credential={credential_id}:"
                    f"device={device_id or '-'}:original={original_amount}:"
                    f"discount={discount_amount}:final={amount}:"
                    f"balance_before={balance_before}:balance_after={balance_after}:"
                    f"ledger={ledger_reference or '-'}:promo={promo_id or '-'}",
                ),
            )
            c.commit()

        return {
            "transaction_id": tx,
            "status": "completed",
            "original_amount": original_amount,
            "discount_amount": discount_amount,
            "final_amount": amount,
            "amount": amount,
            "method": method,
            "provider": provider,
            "device_id": device_id,
            "promo_id": promo_id,
            "ledger_reference": ledger_reference,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "balance": balance_after,
        }

    @staticmethod
    def _balance_on_connection(c, account_id):
        row = c.execute(
            "SELECT COALESCE(SUM(CASE WHEN direction='credit' THEN amount ELSE -amount END),0) "
            "FROM financial_ledger WHERE account_id=?",
            (account_id,),
        ).fetchone()
        return int(row[0])
