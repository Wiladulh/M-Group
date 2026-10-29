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
        pin=None,
        original_amount=None,
        discount_amount=0,
        promo_id=None,
        device_authenticated_vending=False,
        transaction_source="WEBUI",
        device_hardware_id=None,
    ):
        if transaction_source not in {"WEBUI", "CASHIER"}:
            raise ValueError("invalid_transaction_source")
        if device_hardware_id is not None and (not isinstance(device_hardware_id, str) or not device_hardware_id.strip()):
            raise ValueError("invalid_device_hardware_id")
        if transaction_source == "CASHIER" and not device_hardware_id:
            raise ValueError("cashier_device_identity_required")
        if transaction_source != "CASHIER" and device_hardware_id:
            raise ValueError("device_identity_not_allowed_for_transaction_source")
        if not isinstance(device_authenticated_vending, bool):
            raise ValueError("invalid_device_authenticated_vending_flag")
        if method not in {"NFC", "QRIS"}:
            raise ValueError("unsupported_payment_method")
        # QRIS stays disabled until a real provider verification flow exists.
        if method == "QRIS":
            raise ValueError("qris_payment_provider_not_activated")
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

        if method == "NFC" and not device_authenticated_vending:
            if pin is None:
                raise PermissionError("pin_required")
            if not self.identity.verify_credential_pin(credential_id, pin):
                raise PermissionError("invalid_pin")

        if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key.strip()) <= 128:
            raise ValueError("invalid_idempotency_key")
        idempotency_key = idempotency_key.strip()

        with self.db.connect() as c:
            # Serialize retries before checking idempotency and mutating balances.
            c.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                row = c.execute(
                    "SELECT transaction_id,status,credential_id,original_amount,discount_amount,final_amount,"
                    "method,provider,account_id,balance_before,balance_after,promo_id,transaction_source "
                    "FROM payment_transactions WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if row:
                    if (
                        row["account_id"] != account_id
                        or row["credential_id"] != credential_id
                        or row["method"] != method
                        or row["provider"] != provider
                        or row["original_amount"] != original_amount
                        or row["discount_amount"] != discount_amount
                        or row["promo_id"] != promo_id
                        or row["transaction_source"] != transaction_source
                        or (reference is not None and row["transaction_id"] != reference)
                    ):
                        raise ValueError("idempotency_key_conflict")

                    association = c.execute(
                        "SELECT hardware_id FROM payment_device_associations WHERE transaction_id=?",
                        (row["transaction_id"],),
                    ).fetchone()
                    if transaction_source == "CASHIER":
                        # Never let a retry retroactively claim an old transaction
                        # for a different/unrecorded device.
                        if not association or association["hardware_id"] != device_hardware_id:
                            raise ValueError("idempotency_key_conflict")
                    elif association:
                        raise ValueError("idempotency_key_conflict")

                    return {
                        "transaction_id": row["transaction_id"],
                        "status": row["status"],
                        "original_amount": row["original_amount"],
                        "discount_amount": row["discount_amount"],
                        "final_amount": row["final_amount"],
                        "method": row["method"],
                        "provider": row["provider"],
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
                "idempotency_key,original_amount,discount_amount,final_amount,"
                "promo_id,balance_before,balance_after,transaction_source) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    tx, credential_id, account_id, amount, "completed", method, provider,
                    idempotency_key, original_amount, discount_amount, amount, promo_id,
                    balance_before, balance_after, transaction_source,
                ),
            )
            if device_hardware_id:
                c.execute(
                    "INSERT INTO payment_device_associations(transaction_id,hardware_id) VALUES(?,?)",
                    (tx, device_hardware_id),
                )
            c.execute(
                "INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                (
                    "payment", "payment_transaction", tx,
                    f"completed:{method}:{provider}:credential={credential_id}:"
                    f"device_key_authenticated={str(bool(device_hardware_id or device_authenticated_vending)).lower()}:"
                    f"original={original_amount}:discount={discount_amount}:final={amount}:"
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
