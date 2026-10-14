from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_navigation_tab_ids_match_loaded_page_panes():
    index = (ROOT / "app" / "webui" / "index.html").read_text(encoding="utf-8")
    page_names = ("dashboard", "financial", "member", "payment", "vending", "audit", "devices")
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
