CREATE TABLE IF NOT EXISTS nfc_replacement_intents (
    session_id TEXT PRIMARY KEY REFERENCES nfc_registration_sessions(session_id),
    member_id TEXT NOT NULL REFERENCES identity_members(member_id),
    operator_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
