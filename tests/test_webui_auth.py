from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import app.main as main
from app.core.auth import hash_password, verify_password


def test_password_hash_verifies_without_storing_plaintext():
    encoded = hash_password("strong-test-password")
    assert encoded.startswith("pbkdf2_sha256$")
    assert "strong-test-password" not in encoded
    assert verify_password("strong-test-password", encoded)
    assert not verify_password("wrong-password", encoded)


def test_webui_login_session_authorizes_api_and_logout_revokes_session():
    with TemporaryDirectory() as tmp:
        old = main.get_settings
        main.get_settings = lambda: type(
            "S",
            (),
            {
                "db_path": Path(tmp) / "m-group.db",
                "admin_token": "server-admin-token",
                "admin_username": "admin-test",
                "admin_password_hash": hash_password("strong-test-password"),
            },
        )()
        try:
            client = TestClient(main.create_app())
            denied = client.get("/api/v1/members")
            assert denied.status_code == 401

            bad_login = client.post(
                "/api/v1/auth/login",
                json={"username": "admin-test", "password": "wrong-password"},
            )
            assert bad_login.status_code == 401

            login = client.post(
                "/api/v1/auth/login",
                json={"username": "admin-test", "password": "strong-test-password"},
            )
            assert login.status_code == 200
            assert login.json()["authenticated"] is True
            assert "m_group_session" in login.cookies

            session = client.get("/api/v1/auth/session")
            assert session.status_code == 200
            assert session.json()["username"] == "admin-test"

            authorized = client.get("/api/v1/members")
            assert authorized.status_code == 200

            account_update = client.post(
                "/api/v1/auth/account",
                headers={"Origin": "http://testserver"},
                json={
                    "current_password": "strong-test-password",
                    "username": "admin-renamed",
                    "new_password": "another-strong-password",
                },
            )
            assert account_update.status_code == 200
            assert account_update.json()["username"] == "admin-renamed"
            assert client.get("/api/v1/auth/session").json()["username"] == "admin-renamed"

            logout = client.post(
                "/api/v1/auth/logout",
                headers={"Origin": "http://testserver"},
            )
            assert logout.status_code == 200
            assert logout.json()["authenticated"] is False

            denied_after_logout = client.get("/api/v1/members")
            assert denied_after_logout.status_code == 401

            old_credentials = client.post(
                "/api/v1/auth/login",
                json={"username": "admin-test", "password": "strong-test-password"},
            )
            assert old_credentials.status_code == 401
            new_credentials = client.post(
                "/api/v1/auth/login",
                json={"username": "admin-renamed", "password": "another-strong-password"},
            )
            assert new_credentials.status_code == 200
        finally:
            main.get_settings = old
