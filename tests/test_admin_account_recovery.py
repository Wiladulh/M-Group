from pathlib import Path
from tempfile import TemporaryDirectory

import app.cli as cli
from app.core.auth import hash_password, verify_password
from app.core.db import Database


def test_reset_admin_account_changes_username_password_and_revokes_sessions(monkeypatch):
    with TemporaryDirectory() as tmp:
        settings = type(
            "S",
            (),
            {"db_path": Path(tmp) / "m-group.db", "admin_username": "configured-admin"},
        )()
        db = Database(settings.db_path)
        db.migrate()
        now = 100
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO webui_admin_accounts(username,password_hash,updated_at) VALUES(?,?,?)",
                ("old-admin", hash_password("old-password-123"), now),
            )
            conn.execute(
                """INSERT INTO webui_sessions
                   (session_hash,username,created_at,last_seen,expires_at)
                   VALUES(?,?,?,?,?)""",
                ("session-hash", "old-admin", now, now, now + 43200),
            )
            conn.commit()

        monkeypatch.setattr(cli, "get_settings", lambda: settings)
        monkeypatch.setattr("sys.argv", ["m-group", "reset-admin-account"])
        monkeypatch.setattr("builtins.input", lambda _prompt: "new-admin")
        answers = iter(["new-password-123", "new-password-123"])
        monkeypatch.setattr(cli, "getpass", lambda _prompt: next(answers))
        cli.main()

        with db.connect() as conn:
            accounts = conn.execute("SELECT username,password_hash FROM webui_admin_accounts").fetchall()
            session = conn.execute(
                "SELECT revoked_at FROM webui_sessions WHERE session_hash=?", ("session-hash",)
            ).fetchone()

        assert len(accounts) == 1
        assert accounts[0]["username"] == "new-admin"
        assert verify_password("new-password-123", accounts[0]["password_hash"])
        assert not verify_password("old-password-123", accounts[0]["password_hash"])
        assert session["revoked_at"] is not None
