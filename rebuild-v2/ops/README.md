# Operations v2

The `.env.example` file documents the first-install environment for the clean-room v2 backend. Copy it to a protected service environment file, replace every placeholder with unique secrets, and restrict the file to the service account/root.

- `MGROUP_ADMIN_USERNAME` and `MGROUP_ADMIN_PASSWORD` create the first super-admin only when the v2 database is empty.
- `MGROUP_DEVICE_KEY_PEPPER` must be a separate, stable secret. Losing it invalidates device-key and admin-session hashes.
- `MGROUP_DB_PATH` must point to persistent storage outside the application checkout.
- The current top-level `installer/install.sh` still packages the legacy `app/` runtime. Do not treat it as a v2 installer or use it to deploy the clean-room backend.
- A dedicated v2 service installer, systemd/OpenRC unit, protected secret-file provisioning, backup/restore procedures, health checks, and release checklist remain to be completed.

Rules:
- Do not commit real secrets or production data.
- CI and local development must use isolated databases.
- Backup/restore must be rehearsed before cutover.
- No deployment or production database mutation occurs automatically from a code merge.
