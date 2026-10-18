CREATE TABLE IF NOT EXISTS webui_sessions (
    session_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    revoked_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_webui_sessions_expiry ON webui_sessions(expires_at);
CREATE TABLE IF NOT EXISTS webui_login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_key TEXT NOT NULL,
    attempted_at INTEGER NOT NULL,
    succeeded INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_webui_login_attempts_client_time
    ON webui_login_attempts(client_key, attempted_at);
INSERT OR IGNORE INTO system_meta(key,value) VALUES('schema_version','021');
