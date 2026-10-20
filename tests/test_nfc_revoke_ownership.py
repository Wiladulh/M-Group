from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import app.main as main
from app.identity.management import MemberManagementService


from conftest import login_admin
def test_nfc_revoke_rejects_card_owned_by_another_member():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        old_settings = main.get_settings
        main.get_settings = lambda: type(
            "Settings",
            (),
            {"db_path": root / "m-group.db",},
        )()
        try:
            client = TestClient(main.create_app())
            members = MemberManagementService(client.app.state.db)
            members.create("member-a", "Member A")
            members.create("member-b", "Member B")
            members.add_card("member-b", "card-uid-b")

            with client.app.state.db.connect() as c:
                card = c.execute(
                    "SELECT card_id FROM member_nfc_cards WHERE member_id=?",
                    ("member-b",),
                ).fetchone()
            response = client.post(
                f"/api/v1/members/member-a/nfc-cards/{card['card_id']}/revoke",
                headers=login_admin(client),
            )
            assert response.status_code == 404
            with client.app.state.db.connect() as c:
                status = c.execute(
                    "SELECT status FROM member_nfc_cards WHERE card_id=?",
                    (card["card_id"],),
                ).fetchone()["status"]
            assert status == "active"
        finally:
            main.get_settings = old_settings
