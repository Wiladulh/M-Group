# M-Group v2 backend

Python 3.12+ / FastAPI / SQLite starter runtime. From `rebuild-v2/backend`:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export MGROUP_ADMIN_USERNAME='admin'
export MGROUP_ADMIN_PASSWORD='replace-with-a-unique-password-of-12-to-128-characters'
export MGROUP_DEVICE_KEY_PEPPER='set-a-separate-random-secret'
uvicorn mgroup_backend.main:app --host 127.0.0.1 --port 8080
```

The backend serves the canonical v2 WebUI from the same origin at `/`; page fragments and assets are served from `/pages/` and `/assets/`. The first run creates the clean v2 database at `rebuild-v2/var/mgroup-v2.sqlite3` unless `MGROUP_DB_PATH` is set. Do not expose the service publicly until TLS/reverse proxy, rate limiting, operational secrets, backup/restore, and security review are configured. `GET /api/v2/health` is a liveness check; `GET /api/v2/ready` also checks database access.

Implemented server surface currently includes health/readiness, username/password admin login with HttpOnly session cookies, role-based admin authorization, device provisioning, device-key authentication context, member creation/listing, PBKDF2-hashed optional member PIN, hashed NFC card enrollment, idempotent top-ups, five fixed vending product slots, product updates, NFC vending purchase with atomic balance/stock changes, idempotency, dispense-result reconciliation/refund, and audit listing. QRIS provider integration, PIN/card management policies and rate limiting, deployment hardening, and full recovery/security review remain unfinished gates. A failed dispense must be reported by the vending client to `/api/v2/vending/transactions/{transaction_id}/dispense-result`; a repeated result is idempotent. This is not production-ready until those remaining gates and end-to-end deployment tests pass.


## Administrator login

On a fresh installation, set `MGROUP_ADMIN_USERNAME` and `MGROUP_ADMIN_PASSWORD` before the first server start. The server creates the initial super-admin account only when the admin table is empty; subsequent password changes are made inside WebUI Settings. Admin sessions are random server-side sessions delivered only in an HttpOnly, SameSite=Strict cookie, never a JavaScript-readable bearer token. The browser cookie is a session cookie and the server session expires after 12 hours. All state-changing admin requests and login validate the request Origin when supplied. When deployed behind TLS termination, the reverse proxy must preserve the public `Host` header and overwrite `X-Forwarded-Proto` with `https` so the session cookie is marked Secure. Keep `MGROUP_DEVICE_KEY_PEPPER` stable and secret because it hashes server-side session identifiers. No Admin API Token or Authorization Bearer fallback is accepted by the v2 admin API.

The current repository's top-level `installer/install.sh` still targets the legacy `app/` runtime. Use this README for development/manual v2 startup only; a dedicated production v2 installer and service unit remain outstanding.
