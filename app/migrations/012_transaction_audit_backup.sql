-- Transaction separation, cashier deposits and retention metadata.
-- ALTER TABLE compatibility is handled idempotently by Database.migrate().
CREATE TABLE IF NOT EXISTS cashier_deposits(
    transaction_id TEXT PRIMARY KEY,
    hardware_id TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    member_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK(amount>0),
    status TEXT NOT NULL DEFAULT 'pending',
    idempotency_key TEXT UNIQUE,
    balance_before INTEGER,
    balance_after INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_cashier_deposit_created ON cashier_deposits(created_at);
CREATE INDEX IF NOT EXISTS ix_cashier_deposit_device ON cashier_deposits(hardware_id,created_at);
CREATE INDEX IF NOT EXISTS ix_cashier_deposit_member ON cashier_deposits(member_id,created_at);
