# M-Group v2 backend

Python 3.12+ / FastAPI / SQLite starter runtime. From `rebuild-v2/backend`:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export MGROUP_ADMIN_TOKEN='replace-with-a-long-random-secret'
export MGROUP_DEVICE_KEY_PEPPER='set-a-separate-random-secret'
uvicorn mgroup_backend.main:app --host 127.0.0.1 --port 8080
```

The first run creates the clean v2 database at `rebuild-v2/var/mgroup-v2.sqlite3` unless `MGROUP_DB_PATH` is set. Do not expose the service publicly until TLS/reverse proxy, rate limiting, operational secrets, backup/restore, and security review are configured. `GET /api/v2/health` is a liveness check; `GET /api/v2/ready` also checks database access.

Implemented server surface currently includes health/readiness, admin-protected device provisioning, device-key authentication context, member creation/listing, PBKDF2-hashed optional member PIN, hashed NFC card enrollment, idempotent top-ups, five fixed vending product slots, product updates, NFC vending purchase with atomic balance/stock changes, idempotency, dispense-result reconciliation/refund, and audit listing. QRIS provider integration, PIN/card management policies and rate limiting, admin user/session RBAC, deployment hardening, and full recovery/security review remain unfinished gates. A failed dispense must be reported by the vending client to `/api/v2/vending/transactions/{transaction_id}/dispense-result`; a repeated result is idempotent. This is not production-ready until those remaining gates and end-to-end deployment tests pass.
