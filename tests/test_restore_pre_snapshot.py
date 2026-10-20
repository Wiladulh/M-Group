from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import app.main as main
from app.core.backup import create_native_backup


from tests.auth_helpers import login_admin
def test_restore_endpoint_creates_pre_restore_snapshot():
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
            with client.app.state.db.connect() as connection:
                connection.execute(
                    "INSERT INTO identity_members(member_id, name) VALUES(?, ?)",
                    ("current-member", "Current member"),
                )
                connection.commit()

            archive = root / "valid.mgroup.zip"
            create_native_backup(client.app.state.db, archive, include_excel=False)
            response = client.post(
                "/api/v1/backup/restore",
                headers=login_admin(client),
                files={"file": ("valid.mgroup.zip", archive.read_bytes(), "application/zip")},
            )
            assert response.status_code == 200, response.text
            snapshot_name = response.json()["pre_restore_backup"]
            assert snapshot_name.startswith("M-Group_PRE_RESTORE_")
            snapshot = root / "backups" / snapshot_name
            assert snapshot.is_file()
            assert snapshot.stat().st_size > 0
        finally:
            main.get_settings = old_settings
