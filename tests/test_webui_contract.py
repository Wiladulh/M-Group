from pathlib import Path
import re
import shutil
import subprocess
import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_navigation_tab_ids_match_loaded_page_panes():
    index = (ROOT / "app" / "webui" / "index.html").read_text(encoding="utf-8")
    page_names = ("dashboard", "member", "financial", "payment", "vending", "cashier", "devices", "audit", "settings")
    buttons = set(re.findall(r'data-tab="([^"]+)"', index))
    pane_ids = set()
    for name in page_names:
        page = (ROOT / "app" / "webui" / "pages" / f"{name}.html").read_text(encoding="utf-8")
        pane_ids.update(re.findall(r'id="tab-([^"]+)"', page))
    assert buttons == pane_ids


def test_dashboard_data_fetch_uses_session_cookie_and_reports_loading_errors():
    js = (ROOT / "app" / "webui" / "assets" / "js" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "app" / "webui" / "index.html").read_text(encoding="utf-8")
    assert "X-M-Group-Admin-Token" not in js
    assert "dashboardAdminToken" not in js
    assert "credentials" in js
    assert "restoreSession()" in js
    assert "sessionStorage.setItem('m-group-active-tab', tabName)" in js
    assert "sessionStorage.getItem('m-group-active-tab')" in js
    assert "validTabs.includes(savedTab)" in js
    assert "Gagal memuat JavaScript WebUI" in index
    assert "unhandledrejection" in index


def test_vending_ui_uses_fixed_product_ids_and_server_machine_list():
    page = (ROOT / "app" / "webui" / "pages" / "vending.html").read_text(encoding="utf-8")
    js = (ROOT / "app" / "webui" / "assets" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'id="productSlot"' not in page
    assert 'value="1">Product ID 1' in page
    assert 'value="5">Product ID 5' in page
    assert 'id="loadVendingMachines"' in page
    assert "function loadVendingMachines" in js
    assert "product_id_must_be_1_to_5" not in js

def test_webui_javascript_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable in this test environment")
    result = subprocess.run(
        [node, "--check", str(ROOT / "app" / "webui" / "assets" / "js" / "app.js")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
