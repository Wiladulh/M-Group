"""Test helpers for migration from admin-token headers to session cookies."""
import time
from urllib.parse import urlsplit
from starlette.testclient import TestClient as StarletteTestClient
from app.core.auth import hash_session_token

_original_request = StarletteTestClient.request

def _request_with_test_session(self, method, url, *args, **kwargs):
    headers = dict(kwargs.get("headers") or {})
    supplied = headers.pop("X-M-Group-Admin-Token", None)
    configured = getattr(getattr(self.app.state, "settings", None), "admin_token", None)
    if supplied and configured and supplied == configured:
        raw = "pytest-session-for-legacy-admin-header"
        now = int(time.time())
        digest = hash_session_token(raw)
        with self.app.state.db.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO webui_sessions
                   (session_hash,username,created_at,last_seen,expires_at)
                   VALUES(?,?,?,?,?)""",
                (digest, "pytest-admin", now, now, now + 3600),
            )
            conn.commit()
        self.cookies.set("m_group_session", raw, path="/")
        if method.upper() not in {"GET", "HEAD", "OPTIONS"} and "Origin" not in headers:
            parsed = urlsplit(str(self.base_url))
            headers["Origin"] = f"{parsed.scheme}://{parsed.netloc}"
    if "headers" in kwargs or supplied:
        kwargs["headers"] = headers
    return _original_request(self, method, url, *args, **kwargs)

StarletteTestClient.request = _request_with_test_session
