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
    nik TEXT UNIQUE,
    phone TEXT,
    email TEXT,
    profile_json TEXT NOT NULL DEFAULT '{}',
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
    label TEXT,
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
        CHECK (transaction_type IN ('purchase', 'cashier_payment', 'top_up', 'withdrawal', 'refund', 'adjustment', 'transfer')),
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

CREATE TABLE IF NOT EXISTS admin_users (
    admin_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('super_admin','operator','auditor')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS admin_sessions (
    session_id TEXT PRIMARY KEY,
    admin_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TEXT,
    FOREIGN KEY (admin_id) REFERENCES admin_users(admin_id)
);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_user_expiry ON admin_sessions(admin_id,expires_at,revoked_at);
CREATE TABLE IF NOT EXISTS admin_login_attempts (
    username TEXT PRIMARY KEY,
    failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    locked_until TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS product_slots (
    registry_id TEXT NOT NULL,
    product_id INTEGER NOT NULL CHECK (product_id BETWEEN 1 AND 5),
    name TEXT NOT NULL,
    price_minor INTEGER NOT NULL CHECK (price_minor >= 0),
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    capacity INTEGER NOT NULL DEFAULT 0 CHECK (capacity >= 0 AND stock <= capacity),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
    image_path TEXT,
    nfc_promo_percent INTEGER NOT NULL DEFAULT 0 CHECK (nfc_promo_percent BETWEEN 0 AND 0),
    qris_promo_percent INTEGER NOT NULL DEFAULT 0 CHECK (qris_promo_percent BETWEEN 0 AND 0),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (registry_id, product_id),
    FOREIGN KEY (registry_id) REFERENCES device_registry(registry_id)
);

CREATE TABLE IF NOT EXISTS product_images (
    registry_id TEXT NOT NULL,
    product_id INTEGER NOT NULL CHECK (product_id BETWEEN 1 AND 5),
    content_type TEXT NOT NULL,
    image_data BLOB NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size BETWEEN 1 AND 2097152),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (registry_id, product_id),
    FOREIGN KEY (registry_id, product_id) REFERENCES product_slots(registry_id, product_id)
);

CREATE TABLE IF NOT EXISTS pin_attempts (
    card_hash TEXT NOT NULL,
    hardware_id TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    locked_until TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (card_hash, hardware_id)
);

CREATE TABLE IF NOT EXISTS pin_card_attempts (
    card_hash TEXT PRIMARY KEY,
    failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    locked_until TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cashiers (
    cashier_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cashier_device_config (
    registry_id TEXT PRIMARY KEY,
    operator_id TEXT NOT NULL,
    operator_name TEXT NOT NULL,
    operator_pin_hash TEXT NOT NULL,
    settlement_account_id TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    locked_until TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (registry_id) REFERENCES device_registry(registry_id),
    FOREIGN KEY (settlement_account_id) REFERENCES accounts(account_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cashier_operator_binding ON cashier_device_config(operator_id);

CREATE TABLE IF NOT EXISTS nfc_registration_sessions (
    session_id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    registry_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('scan_pending','waiting_nfc','pin_pending','processing','completed','failed','expired')),
    card_uid_hash TEXT,
    card_uid_hint TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL,
    completed_at TEXT,
    error_code TEXT,
    replace_existing INTEGER NOT NULL DEFAULT 0 CHECK (replace_existing IN (0,1)),
    FOREIGN KEY (member_id) REFERENCES members(member_id),
    FOREIGN KEY (registry_id) REFERENCES device_registry(registry_id)
);
CREATE INDEX IF NOT EXISTS idx_nfc_registration_cashier_status
    ON nfc_registration_sessions(registry_id,status,created_at);


