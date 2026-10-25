from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import app.main as main


from tests.auth_helpers import login_admin
def test_daily_audit_report_includes_last_second_of_day():
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
            with client.app.state.db.connect() as c:
                c.execute(
                    """INSERT INTO cashier_deposits
                       (transaction_id,hardware_id,credential_id,member_id,account_id,
                        amount,status,created_at,completed_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        "cash-last-second",
                        "cashier-1",
                        "credential-1",
                        "member-1",
                        "account-1",
                        1000,
                        "completed",
                        "2026-01-01 23:59:59",
                        "2026-01-01 23:59:59",
                    ),
                )
                c.commit()

            response = client.get(
                "/api/v1/audit/report?source=CASHIER&period=day&date=2026-01-01",
                headers=login_admin(client),
            )
            assert response.status_code == 200, response.text
            assert response.json()["start"] == "2026-01-01"
            assert response.json()["end"] == "2026-01-02"
            assert [row["transaction_id"] for row in response.json()["transactions"]] == [
                "cash-last-second"
            ]
        finally:
            main.get_settings = old_settings
