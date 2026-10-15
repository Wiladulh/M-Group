# M-Group Linux installer

The installer supports Linux distributions that provide Python 3.10+ and Python venv, including Debian/Ubuntu, Alpine/postmarketOS, Fedora, Arch and similar systems. It uses a Python virtual environment and does not require Docker.

## Install on a VPS or Linux host

Clone the repository and install as a system service (requires root):

```sh
git clone https://github.com/Wiladulh/M-Group.git
cd M-Group
sudo sh installer/install.sh --system
```

The installer builds an isolated environment, installs the API/WebUI, creates a persistent data directory and configuration file, and registers/starts a service when systemd or OpenRC is available. In an interactive system install it prompts for listen address, port, application directory, database/data directory, configuration directory, the admin API token, and an optional initial Cashier operator PIN. Secret inputs are hidden while typing. Leave the admin token blank to generate a cryptographically random token; save a generated token from the installer output. Leave the operator PIN blank to configure it later from the admin WebUI. There is no shared default operator PIN. If an initial PIN is supplied, the installer stores only its hash in SQLite and removes the one-time plaintext setting from the environment file after successful first initialization. On non-interactive runs, defaults are applied and an admin token is generated automatically; the operator PIN remains unset until explicitly configured. SQLite data is kept outside the application directory, so upgrades/reinstalls do not delete the database. Re-running the system installer reuses saved install prefix, data directory, listen address, port, and admin token from the existing environment file unless explicitly overridden with environment variables or changed at the interactive prompts; this avoids accidentally starting a fresh empty instance after a reinstall. The data directory is private to the service account, and the SQLite database file is mode `0600`.

For a per-user installation without a system service:

```sh
sh installer/install.sh --user
```

The installer checks system prerequisites and attempts to install missing Python/pip/venv packages automatically using the detected package manager: apt (Debian/Ubuntu), apk (Alpine/postmarketOS), dnf/yum (Fedora-family), pacman (Arch), or zypper (openSUSE). If needed, it uses sudo to request privilege escalation. Internet access and working distro package repositories are required. It verifies Python 3.10+ and venv before continuing. If configured repositories only offer an older Python, it stops with a clear error rather than installing an incompatible runtime. Set M_GROUP_PYTHON to a Python 3.10+ executable if it is not named python3.

## Access

By default the server binds to `0.0.0.0:8011`, which listens on all IPv4 interfaces and works when the server receives its address by DHCP. This does not configure upstream NAT, cloud security groups, or firewalls; those must allow the chosen port. Because M-Group handles member and financial data, the recommended public deployment is a TLS reverse proxy (for example, Caddy or nginx) with the raw application port blocked from the public internet. For temporary administration, an SSH tunnel is also possible; run this from your own computer:

```sh
ssh -L 8011:127.0.0.1:8011 user@YOUR_VPS
```

Then open `http://127.0.0.1:8011` locally.

To bind only to a specific interface, set `M_GROUP_HOST` to that interface address in the configuration file. Do not expose the raw API port publicly without HTTPS and appropriate network controls.

System install configuration and the admin API token are stored in `/etc/m-group/m-group.env` by default with mode `0640`, owned by root and readable only by root and the service group. Keep this file secret. During installation, the default locations are `/opt/M-Group` (application), `/var/lib/M-Group` (database/data), and `/etc/m-group` (configuration); the installer lets you change these locations interactively. Change `M_GROUP_HOST` or `M_GROUP_PORT` there and restart the service:

- systemd: `sudo systemctl restart m-group`
- OpenRC: `sudo rc-service m-group restart`

## Verify / operate

```sh
curl -fsS http://127.0.0.1:8011/ >/dev/null && echo "M-Group WebUI is responding"
```

- systemd status/logs: `sudo systemctl status m-group`, `sudo journalctl -u m-group -f`
- OpenRC logs: `/var/log/m-group.log`
- Application data: `/var/lib/M-Group`
- CLI: `/opt/M-Group/bin/m-group init` (initializes/migrates the local database)

For custom paths, set `M_GROUP_PREFIX` and `M_GROUP_DATA_DIR` when running the installer. Set `M_GROUP_ADMIN_TOKEN` to preserve/use a known token. Set `M_GROUP_SKIP_SERVICE=1` to install without registering a service.

## Upgrade and uninstall

Run `sudo sh installer/upgrade.sh` from a fresh checkout to update the installed Python package. Back up `/var/lib/M-Group` before upgrades. The uninstall script removes the application environment only and intentionally preserves instance data/configuration.
