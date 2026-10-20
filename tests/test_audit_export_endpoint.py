from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import app.main as main


from conftest import login_admin
def test_audit_export_authorizes_and_returns_workbook():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        old_settings = main.get_settings
        main.get_settings = lambda: type(
            "Settings",
            (),
            {
                "db_path": root / "m-group.db",
                "data_dir": root,
            },
        )()
        try:
            client = TestClient(main.create_app())
            unauthorized = client.get(
                "/api/v1/audit/export.xlsx?source=CASHIER&period=day&date=2026-01-01"
            )
            assert unauthorized.status_code == 401

            response = client.get(
                "/api/v1/audit/export.xlsx?source=CASHIER&period=day&date=2026-01-01",
                headers=login_admin(client),
            )
            assert response.status_code == 200, response.text
            assert response.headers["content-type"].startswith(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            assert response.content[:2] == b"PK"
            assert (root / "exports" / "audit-cashier-day-2026-01-01.xlsx").is_file()
        finally:
            main.get_settings = old_settings
