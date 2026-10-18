import argparse
from getpass import getpass

from app.core.auth import hash_password
from app.core.config import get_settings
from app.core.db import Database


def main():
    parser = argparse.ArgumentParser(prog="M-Group")
    parser.add_argument("command", nargs="?", choices=["init", "hash-password"])
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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
