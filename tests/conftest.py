"""Shared pytest helpers for authenticated WebUI API tests.

Admin tests establish authentication by calling the real login endpoint and use
the session cookie managed by TestClient. No legacy admin-token compatibility
shim or synthetic session insertion is installed here.
"""

from app.core.auth import hash_password


def login_admin(client, username="admin-test", password="strong-test-password"):
    """Log in through the real WebUI endpoint and return optional request headers."""
    settings = client.app.state.settings
    settings.admin_username = username
    settings.admin_password_hash = hash_password(password)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    assert client.cookies.get("m_group_session")
    return {}
