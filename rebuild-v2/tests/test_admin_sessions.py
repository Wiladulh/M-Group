import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from fastapi.testclient import TestClient

import mgroup_backend.main as server


class AdminSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = SimpleNamespace(
            database_path=str(Path(self.temp.name) / "mgroup-test.sqlite3"),
            admin_username="admin",
            admin_password="Initial-Admin-Password-123",
            device_key_pepper="test-only-device-and-session-pepper",
        )
        self.settings_patch = patch.object(server, "settings", self.settings)
        self.settings_patch.start()
        self.client_context = TestClient(server.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.settings_patch.stop()
        self.temp.cleanup()

    def login(self, password=None):
        return self.client.post(
            "/api/v2/admin/auth/login",
            json={"username": "admin", "password": password or self.settings.admin_password},
        )

    def test_login_uses_httponly_session_cookie_not_bearer_token(self):
        cross_origin_login = self.client.post(
            "/api/v2/admin/auth/login",
            headers={"Origin": "https://attacker.example"},
            json={"username": "admin", "password": self.settings.admin_password},
        )
        self.assertEqual(cross_origin_login.status_code, 403)
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["authenticated"])
        self.assertNotIn("access_token", response.json())
        cookie = response.headers.get("set-cookie", "").lower()
        self.assertIn("m_group_admin_session=", cookie)
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertEqual(self.client.get("/api/v2/admin/auth/me").json()["username"], "admin")
        cross_origin = self.client.post(
            "/api/v2/admin/auth/logout",
            headers={"Origin": "https://attacker.example"},
        )
        self.assertEqual(cross_origin.status_code, 403)
        self.assertEqual(self.client.get("/api/v2/admin/auth/me").status_code, 200)

    def test_admin_routes_reject_missing_cookie_and_logout_revokes_session(self):
        self.assertEqual(self.client.get("/api/v2/admin/auth/me").status_code, 401)
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.get("/api/v2/admin/auth/me").status_code, 200)
        self.assertEqual(self.client.post("/api/v2/admin/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/v2/admin/auth/me").status_code, 401)

    def test_password_change_requires_old_password_and_confirmation(self):
        self.assertEqual(self.login().status_code, 200)
        bad = self.client.post(
            "/api/v2/admin/auth/change-password",
            json={
                "current_password": "wrong-password",
                "new_password": "Replacement-Password-456",
                "confirm_password": "Replacement-Password-456",
            },
        )
        self.assertEqual(bad.status_code, 403)
        mismatch = self.client.post(
            "/api/v2/admin/auth/change-password",
            json={
                "current_password": self.settings.admin_password,
                "new_password": "Replacement-Password-456",
                "confirm_password": "Different-Password-456",
            },
        )
        self.assertEqual(mismatch.status_code, 422)
        changed = self.client.post(
            "/api/v2/admin/auth/change-password",
            json={
                "current_password": self.settings.admin_password,
                "new_password": "Replacement-Password-456",
                "confirm_password": "Replacement-Password-456",
            },
        )
        self.assertEqual(changed.status_code, 200)
        self.client.post("/api/v2/admin/auth/logout")
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login("Replacement-Password-456").status_code, 200)


if __name__ == "__main__":
    unittest.main()
