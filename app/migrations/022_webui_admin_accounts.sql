CREATE TABLE IF NOT EXISTS webui_admin_accounts (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
INSERT OR REPLACE INTO system_meta(key,value) VALUES('schema_version','022');
