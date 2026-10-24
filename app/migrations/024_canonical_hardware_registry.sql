-- Canonical device registry for key-authenticated physical hardware.
-- registry_id is an internal database key; hardware_id is the physical identity.
-- No legacy device_id column is created.
CREATE TABLE IF NOT EXISTS device_registry (
    registry_id TEXT PRIMARY KEY,
    hardware_id TEXT UNIQUE,
    device_type TEXT NOT NULL,
    mac_address TEXT,
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'awaiting_device_registration'
        CHECK(status IN ('active','pending','awaiting_device_registration','offline','disabled','maintenance','unassigned')),
    last_seen TEXT,
    auth_key_hash TEXT,
    auth_key_hint TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_device_hardware_id
    ON device_registry(hardware_id) WHERE hardware_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_device_type_status
    ON device_registry(device_type,status);
CREATE INDEX IF NOT EXISTS ix_device_mac
    ON device_registry(mac_address);
CREATE INDEX IF NOT EXISTS ix_device_auth_key_hash
    ON device_registry(auth_key_hash);
CREATE TABLE IF NOT EXISTS device_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hardware_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_device_events_hardware_created
    ON device_events(hardware_id,created_at);
INSERT OR IGNORE INTO system_meta(key,value)
    VALUES('hardware_registry_schema_version','002');
