-- Device authentication uses the provisioned key. No MAC-derived hardware ID is stored.

CREATE INDEX IF NOT EXISTS ix_device_type_status
ON device_registry(device_type,status);
