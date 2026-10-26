-- M-Group v2 canonical clean-install schema.
-- No legacy compatibility columns or tables are included.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS device_registry (
    registry_id TEXT PRIMARY KEY,
    hardware_id TEXT UNIQUE,
    device_type TEXT NOT NULL CHECK (device_type IN ('cashier', 'vending')),
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'active', 'disabled', 'revoked')),
    mac_address TEXT,
    device_key_hash TEXT,
    device_key_hint TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT,
    revoked_at TEXT,
    CHECK (hardware_id IS NULL OR length(trim(hardware_id)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_device_registry_type_status
    ON device_registry(device_type, status);

CREATE INDEX IF NOT EXISTS idx_device_registry_mac
    ON device_registry(mac_address);

CREATE TABLE IF NOT EXISTS device_events (
    event_id TEXT PRIMARY KEY,
    registry_id TEXT,
    hardware_id TEXT,
    event_type TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (registry_id) REFERENCES device_registry(registry_id)
);

CREATE INDEX IF NOT EXISTS idx_device_events_hardware_time
    ON device_events(hardware_id, created_at);

CREATE TABLE IF NOT EXISTS members (
    member_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'suspended', 'closed')),
    pin_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS member_cards (
    card_id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    card_uid_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled', 'revoked')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (member_id) REFERENCES members(member_id)
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    member_id TEXT UNIQUE,
    account_type TEXT NOT NULL CHECK (account_type IN ('member', 'merchant', 'system')),
    currency TEXT NOT NULL DEFAULT 'IDR',
    balance_minor INTEGER NOT NULL DEFAULT 0 CHECK (balance_minor >= 0),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'frozen', 'closed')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (member_id) REFERENCES members(member_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    hardware_id TEXT,
    member_id TEXT,
    transaction_type TEXT NOT NULL
        CHECK (transaction_type IN ('purchase', 'cashier_payment', 'top_up', 'refund', 'adjustment', 'transfer')),
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    currency TEXT NOT NULL DEFAULT 'IDR',
    status TEXT NOT NULL
        CHECK (status IN ('pending', 'succeeded', 'declined', 'reversed')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY (member_id) REFERENCES members(member_id)
);

CREATE INDEX IF NOT EXISTS idx_transactions_member_time
    ON transactions(member_id, created_at);

CREATE INDEX IF NOT EXISTS idx_transactions_hardware_time
    ON transactions(hardware_id, created_at);

CREATE TABLE IF NOT EXISTS ledger_entries (
    entry_id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('debit', 'credit')),
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id),
    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
);

CREATE INDEX IF NOT EXISTS idx_ledger_transaction
    ON ledger_entries(transaction_id);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_id TEXT PRIMARY KEY,
    actor_type TEXT NOT NULL,
    actor_id TEXT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    request_id TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_entity_time
    ON audit_events(entity_type, entity_id, created_at);
