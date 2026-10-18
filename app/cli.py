import argparse
from getpass import getpass

from app.core.auth import hash_password
from app.core.config import get_settings
from app.core.db import Database


def main():
    parser = argparse.ArgumentParser(prog="M-Group")
    parser.add_argument("command", nargs="?", choices=["init", "hash-password", "reset-admin-password"])
    args = parser.parse_args()

    if args.command == "init":
        settings = get_settings()
        Database(settings.db_path).migrate()
        print(settings.db_path)
    elif args.command == "hash-password":
        password = getpass("Password admin baru: ")
        confirmation = getpass("Ulangi password admin: ")
        if not password or password != confirmation:
            parser.error("password kosong atau konfirmasi tidak cocok")
        print(hash_password(password))
    elif args.command == "reset-admin-password":
        settings = get_settings()
        if not settings.admin_username:
            parser.error("M_GROUP_ADMIN_USERNAME belum dikonfigurasi")
        password = getpass("Password admin baru: ")
        confirmation = getpass("Ulangi password admin: ")
        if len(password) < 8 or password != confirmation:
            parser.error("password minimal 8 karakter dan konfirmasi harus cocok")
        db = Database(settings.db_path)
        db.migrate()
        now = int(__import__("time").time())
        with db.connect() as c:
            c.execute(
                """INSERT INTO webui_admin_accounts(username,password_hash,updated_at)
                   VALUES(?,?,?)
                   ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash,
                   updated_at=excluded.updated_at""",
                (settings.admin_username, hash_password(password), now),
            )
            c.execute("UPDATE webui_sessions SET revoked_at=? WHERE revoked_at IS NULL", (now,))
            c.commit()
        print("Password admin direset. Semua sesi WebUI dicabut; login ulang diperlukan.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
