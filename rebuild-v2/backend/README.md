# M-Group v2 backend

Python 3.12+ / FastAPI / SQLite starter runtime. From `rebuild-v2/backend`:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export MGROUP_ADMIN_TOKEN='replace-with-a-long-random-secret'
export MGROUP_DEVICE_KEY_PEPPER='set-a-separate-random-secret'
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

The first run creates the clean v2 database at `rebuild-v2/var/mgroup-v2.sqlite3` unless `MGROUP_DB_PATH` is set. Do not expose the service publicly until TLS/reverse proxy, rate limiting, operational secrets, backup/restore, and security review are configured. `GET /api/v2/health` is a liveness check; `GET /api/v2/ready` also checks database access.

Initial implemented server surface: admin-protected device registration/provisioning, device-key authentication context, member creation/listing, idempotent member top-up ledger entries, vending registry/product slots 1–5, product updates, and audit listing. QRIS/NFC payment execution, card enrollment/PIN workflows, stock-consuming purchases, reversal, user/session management, rate limiting, and production deployment hardening remain unfinished gates. This scaffold is not production-ready yet.
