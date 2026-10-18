import argparse
from getpass import getpass
import re
import time

from app.core.auth import hash_password
from app.core.config import get_settings
from app.core.db import Database


def _read_new_password(parser):
    password = getpass("Password admin baru: ")
    confirmation = getpass("Ulangi password admin: ")
    if len(password) < 8 or password != confirmation:
        parser.error("password minimal 8 karakter dan konfirmasi harus cocok")
    return password


def main():
    parser = argparse.ArgumentParser(prog="M-Group")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["init", "hash-password", "reset-admin-password", "reset-admin-account"],
    )
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
    elif args.command in {"reset-admin-password", "reset-admin-account"}:
        settings = get_settings()
        username = settings.admin_username
        if args.command == "reset-admin-account":
            username = input("Username admin baru: ").strip()
            if not 3 <= len(username) <= 64 or not re.fullmatch(r"[A-Za-z0-9._-]+", username):
                parser.error("username harus 3-64 karakter: huruf, angka, titik, garis bawah, atau tanda hubung")
        elif not username:
            parser.error("M_GROUP_ADMIN_USERNAME belum dikonfigurasi")

        password = _read_new_password(parser)
        db = Database(settings.db_path)
        db.migrate()
        now = int(time.time())
        password_hash = hash_password(password)
        with db.connect() as c:
            if args.command == "reset-admin-account":
                c.execute("DELETE FROM webui_admin_accounts")
                c.execute(
                    "INSERT INTO webui_admin_accounts(username,password_hash,updated_at) VALUES(?,?,?)",
                    (username, password_hash, now),
                )
            else:
                account = c.execute(
                    "SELECT username FROM webui_admin_accounts ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
                if account:
                    c.execute(
                        "UPDATE webui_admin_accounts SET password_hash=?,updated_at=? WHERE username=?",
                        (password_hash, now, account["username"]),
                    )
                else:
                    c.execute(
                        "INSERT INTO webui_admin_accounts(username,password_hash,updated_at) VALUES(?,?,?)",
                        (username, password_hash, now),
                    )
            c.execute("UPDATE webui_sessions SET revoked_at=? WHERE revoked_at IS NULL", (now,))
            c.commit()
        if args.command == "reset-admin-account":
            print("Akun admin direset. Semua sesi WebUI dicabut; login ulang dengan username dan password baru.")
        else:
            print("Password admin direset. Semua sesi WebUI dicabut; login ulang diperlukan.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
