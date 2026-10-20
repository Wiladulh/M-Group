"""Helpers for authenticated WebUI API tests.

Admin tests establish authentication by calling the real login endpoint and use
the session cookie managed by TestClient. No synthetic sessions or legacy token
compatibility are used.
"""

from app.core.auth import hash_password


def login_admin(client, username="admin-test", password="strong-test-password"):
    """Log in through the real WebUI endpoint and return optional request headers."""
    settings = client.app.state.settings
    object.__setattr__(settings, "admin_username", username)
    object.__setattr__(settings, "admin_password_hash", hash_password(password))
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    assert response.cookies.get("m_group_session")
    # Emulate a browser's same-origin header for authenticated WebUI requests.
    client.headers.update({"Origin": "http://testserver"})
    return {"Origin": "http://testserver"}
