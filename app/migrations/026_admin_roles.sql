CREATE TABLE IF NOT EXISTS admin_users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('super_admin','operator','auditor')),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    created_by TEXT
);
CREATE TABLE IF NOT EXISTS admin_security_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_username TEXT,
    event_type TEXT NOT NULL,
    target_username TEXT,
    detail TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_security_events_created
    ON admin_security_events(created_at);
CREATE INDEX IF NOT EXISTS idx_admin_users_role_active
    ON admin_users(role,is_active);
INSERT OR IGNORE INTO system_meta(key,value) VALUES('admin_roles_schema_version','001');
