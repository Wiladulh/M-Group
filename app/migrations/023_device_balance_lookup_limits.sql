CREATE TABLE IF NOT EXISTS device_balance_lookup_limits (
    hardware_id TEXT NOT NULL,
    card_uid_hash TEXT NOT NULL,
    last_lookup_at REAL NOT NULL,
    PRIMARY KEY(hardware_id, card_uid_hash)
);
CREATE INDEX IF NOT EXISTS idx_device_balance_lookup_time
    ON device_balance_lookup_limits(last_lookup_at);
INSERT OR REPLACE INTO system_meta(key,value) VALUES('schema_version','023');
