-- Bind each vending machine to one server-provisioned vending Device Key.
-- The key hash is not a hardware identifier and is never exposed to firmware.
CREATE TABLE IF NOT EXISTS vending_machine_key_bindings (
    machine_id TEXT PRIMARY KEY REFERENCES vending_machines(machine_id) ON DELETE CASCADE,
    auth_key_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
