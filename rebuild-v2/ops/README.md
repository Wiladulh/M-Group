# Operations v2

## Dedicated clean-room v2 installer

From the repository checkout on a systemd Linux host with Python 3.12+ and venv support:

```sh
sudo sh rebuild-v2/ops/install-v2.sh
```

The installer is deliberately separate from the legacy top-level `installer/install.sh`. It does not migrate, overwrite, or start the legacy `app/` runtime.

Defaults:
- Application releases: `/opt/M-Group-v2/releases/` with an atomic `current` symlink.
- Persistent SQLite data: `/var/lib/M-Group-v2/`.
- Protected environment: `/etc/m-group-v2/mgroup-v2.env` (mode 0640; root and the dedicated `m-group-v2` service group only).
- Service: `m-group-v2.service`, running as the unprivileged `m-group-v2` account.
- Bind: `127.0.0.1:8080` by default; place a TLS reverse proxy in front for remote access.

On first installation the installer generates an initial admin password and a separate stable `MGROUP_DEVICE_KEY_PEPPER` if they are not supplied in the environment. The generated admin username/password are printed once to the root terminal; save them securely. The environment file is preserved on later runs, so reinstalling/upgrading does not rotate credentials or the pepper. The database lives outside the release directory and is not removed by this installer.

Optional environment overrides are documented by `install-v2.sh --help`. Use `--no-service` only for staging: it installs a release and secrets but does not register or start systemd. The installer requires Python 3.12+, a systemd host for service mode, and `useradd` to create its restricted service account.

## Operational rules

- Keep `MGROUP_DEVICE_KEY_PEPPER` stable and secret. Losing it invalidates device-key and admin-session hashes.
- Never commit real secrets or production data.
- Keep `MGROUP_DB_PATH` on persistent storage outside the application checkout.
- Keep the default localhost bind unless TLS, firewall policy, and reverse-proxy headers are configured.
- CI and local development must use isolated databases.
- Rehearse backup/restore and verify `/api/v2/health` and `/api/v2/ready` before any cutover.
- No deployment or production database mutation occurs automatically from a code merge.
- Production release still requires CI regression tests, Cashier/Vending firmware builds, device acceptance, backup/restore drill, and security review.
