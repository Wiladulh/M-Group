-- Member maintenance: auditable, idempotent corrections and NFC replacement intent.
CREATE TABLE IF NOT EXISTS financial_corrections (
    correction_id TEXT PRIMARY KEY,
    original_transaction_id TEXT NOT NULL REFERENCES financial_transactions(transaction_id),
    member_id TEXT NOT NULL REFERENCES identity_members(member_id),
    account_id TEXT NOT NULL REFERENCES financial_accounts(account_id),
    original_amount INTEGER NOT NULL CHECK(original_amount > 0),
    corrected_amount INTEGER NOT NULL CHECK(corrected_amount > 0),
    adjustment_amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    operator_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_financial_corrections_member_created
ON financial_corrections(member_id, created_at);
