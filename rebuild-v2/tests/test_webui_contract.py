import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "webui"
BACKEND = ROOT / "backend" / "mgroup_backend" / "main.py"
FIRMWARE = ROOT / "firmware" / "src" / "vending.cpp"
CASHIER_FIRMWARE = ROOT / "firmware" / "src" / "cashier.cpp"


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
        cls.cashier_firmware = CASHIER_FIRMWARE.read_text(encoding="utf-8")

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


    def test_only_admin_and_member_actor_model_is_exposed(self):
        self.assertNotIn("operator", self.api + self.app + self.html + self.settings)
        self.assertNotIn("auditor", self.backend)
        self.assertNotIn("/admin/users", self.backend)
        self.assertNotIn("pertamini", self.html.lower())
        self.assertNotIn("pinjaman", self.html.lower() + self.settings.lower())
        self.assertNotIn("loans", self.app.lower())
        self.assertIn("UID-", self.backend)

    def test_member_transaction_pin_is_required_on_cashier_and_vending(self):
        self.assertIn("pin_hash", self.backend)
        self.assertIn("verify_pin(pin, member['pin_hash'])", self.backend)
        self.assertIn("pin_pending", self.app)
        self.assertIn('body["pin"]=pinDigits', self.cashier_firmware)
        self.assertIn('doc["pin"]=pinDigits', self.firmware)
        self.assertIn("/api/v2/cashier/payments", self.cashier_firmware)
        self.assertIn("/api/v2/vending/purchases", self.firmware)
        self.assertIn("PIN transaksi", (WEBUI / "pages" / "member.html").read_text(encoding="utf-8"))

    def test_topup_is_admin_webui_only_and_never_device_pin_flow(self):
        self.assertIn('"/finance/top-ups"', self.app)
        self.assertIn("@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin_session)])", self.backend)
        self.assertNotIn("/api/v2/cashier/top-ups", self.backend)
        self.assertNotIn("/api/v2/vending/top-ups", self.backend)
        self.assertNotIn("TOPUP", self.cashier_firmware.upper())
        self.assertNotIn("TOPUP", self.firmware.upper())

    def test_financial_ui_is_topup_only_and_requires_confirmation(self):
        financial = (WEBUI / "pages" / "financial.html").read_text(encoding="utf-8")
        self.assertIn("Top Up Saldo Member", financial)
        self.assertIn("Keterangan penerimaan uang tunai", financial)
        self.assertIn('id="financialRequestId"', financial)
        self.assertNotIn("Penarikan", financial)
        self.assertNotIn('id="direction"', financial)
        self.assertIn("window.confirm(confirmation)", self.app)
        self.assertIn('request("/finance/top-ups"', self.app)
        self.assertNotIn("/finance/withdrawals", self.app)
        self.assertNotIn("/api/v2/finance/withdrawals", self.backend)

    def test_webui_styles_include_mobile_breakpoints(self):
        self.assertRegex(self.css, r"@media\s*\(max-width\s*:")


if __name__ == "__main__":
    unittest.main()
