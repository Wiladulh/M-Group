from pathlib import Path
import re


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


def test_dashboard_data_fetch_requires_admin_token_and_reports_loading_errors():
    js = (ROOT / "app" / "webui" / "assets" / "js" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "app" / "webui" / "index.html").read_text(encoding="utf-8")
    assert "X-M-Group-Admin-Token':token" in js
    assert "dashboardAdminToken" in js
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
