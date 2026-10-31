import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "webui"
BACKEND = ROOT / "backend" / "mgroup_backend" / "main.py"
FIRMWARE = ROOT / "firmware" / "src" / "vending.cpp"


class WebUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = (WEBUI / "assets" / "js" / "api.js").read_text(encoding="utf-8")
        cls.app = (WEBUI / "assets" / "js" / "app.js").read_text(encoding="utf-8")
        cls.html = (WEBUI / "index.html").read_text(encoding="utf-8")
        cls.settings = (WEBUI / "pages" / "settings.html").read_text(encoding="utf-8")
        cls.css = (WEBUI / "assets" / "css" / "app.css").read_text(encoding="utf-8")
        cls.backend = BACKEND.read_text(encoding="utf-8")
        cls.firmware = FIRMWARE.read_text(encoding="utf-8")

    def test_admin_webui_uses_only_v2_cookie_sessions(self):
        self.assertIn('const basePath = "/api/v2"', self.api)
        self.assertNotIn("/api/v1", self.api + self.app + self.html)
        self.assertNotIn("sessionStorage", self.api)
        self.assertNotIn("Authorization", self.api)
        self.assertIn("/admin/auth/login", self.api)
        self.assertIn("/admin/auth/me", self.api)
        self.assertIn("/admin/auth/logout", self.api)
        self.assertIn("mgroup:unauthorized", self.app)
        self.assertIn("HttpOnly", self.settings)
        self.assertNotIn("Admin API Token", self.html + self.settings)

    def test_member_edit_and_nfc_workflow_are_wired_to_v2_routes(self):
        self.assertIn('data-member-action="edit"', self.app)
        self.assertIn('data-member-action="nfc"', self.app)
        self.assertIn('/admin/members/', self.app)
        self.assertIn('/nfc-registration', self.app)
        self.assertIn("/api/v2/admin/members/{member_id}", self.backend)
        self.assertIn("/api/v2/admin/members/{member_id}/nfc-registration", self.backend)

    def test_product_image_upload_and_vending_delivery_are_wired(self):
        self.assertIn("productImageFile", self.app)
        self.assertIn("/image", self.app)
        self.assertIn("/api/v2/admin/vending/devices/{registry_id}/products/{product_id}/image", self.backend)
        self.assertIn("/api/v2/device/products/{product_id}/image", self.backend)
        self.assertIn("syncProductImage", self.firmware)
        self.assertIn("LittleFS", self.firmware)
        self.assertIn("mbedtls_sha256", self.firmware)

    def test_backup_restore_and_password_change_controls_have_v2_endpoints(self):
        self.assertIn('id="accountSettings"', self.settings)
        self.assertIn("/admin/auth/change-password", self.app)
        self.assertIn("/api/v2/admin/auth/change-password", self.backend)
        self.assertIn("/admin/backup", self.app)
        self.assertIn("/api/v2/admin/backup", self.backend)
        self.assertIn("/api/v2/admin/backup/restore", self.backend)

    def test_webui_styles_include_mobile_breakpoints(self):
        self.assertRegex(self.css, r"@media\\s*\\(max-width\\s*:")


if __name__ == "__main__":
    unittest.main()
