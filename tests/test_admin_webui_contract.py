from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_primary_admin_username_is_fixed_in_installer():
    installer = (ROOT / "installer" / "install.sh").read_text()
    helper = (ROOT / "installer" / "configure-admin-login.sh").read_text()
    assert "ADMIN_USERNAME=admin" in installer
    assert "ADMIN_USERNAME=admin" in helper
    assert "printf \"WebUI admin username" not in helper
    assert "M_GROUP_ADMIN_USERNAME=admin" in installer


def test_legacy_single_admin_migration_renames_account_and_revokes_sessions():
    routes = (ROOT / "app" / "api" / "routes.py").read_text()
    assert "Legacy single-admin account renamed to fixed username admin" in routes
    assert "UPDATE admin_users SET username='admin'" in routes
    assert "UPDATE webui_admin_accounts SET username='admin'" in routes
    assert "UPDATE webui_sessions SET revoked_at=? WHERE username=?" in routes


def test_demo_has_matching_admin_login_password_change_and_logout_flow():
    demo = (ROOT / "demo" / "demo-v2.html").read_text()
    assert 'id="demoLoginForm"' in demo
    assert 'value="admin"' in demo
    assert "demo-admin" in demo
    for page in ("dashboard", "members", "finance", "payment", "vending", "promotions", "cashier", "devices", "transactions", "audit", "settings"):
        assert f'id="page-{page}"' in demo
        assert f'data-page="{page}"' in demo
    assert demo.index('<section class="page" id="page-audit">') < demo.index('<section class="page" id="page-settings">')
    # Count every nested section, not just top-level page sections. Settings
    # intentionally contains two additional sections inside its page wrapper.
    assert len(re.findall(r"<section\\b", demo)) == len(re.findall(r"</section\\s*>", demo))
    assert 'id="demoPasswordForm"' in demo
    assert "old!==demoAdminPassword" in demo
    assert "next.length<12" in demo
    assert "next!==confirm" in demo
    assert 'id="demoLogout"' in demo
    assert "[hidden]{display:none!important}" in demo


def test_webui_has_consistent_responsive_controls_and_password_form():
    css = (ROOT / "app" / "webui" / "assets" / "css" / "app.css").read_text()
    settings = (ROOT / "app" / "webui" / "pages" / "settings.html").read_text()
    assert ".account-password-form" in css
    assert "@media(max-width:760px)" in css
    assert "[hidden]{display:none!important}" in css
    assert 'id="currentAdminPassword"' in settings
    assert 'id="newAdminPassword"' in settings
    assert 'id="confirmAdminPassword"' in settings
