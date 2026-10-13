# M-Group Linux installer

The installer supports Linux distributions that provide Python 3.10+ and Python venv, including Debian/Ubuntu, Alpine/postmarketOS, Fedora, Arch and similar systems. It uses a Python virtual environment and does not require Docker.

## Install on a VPS or Linux host

Clone the repository and install as a system service (requires root):

```sh
git clone https://github.com/Wiladulh/M-Group.git
cd M-Group
sudo sh installer/install.sh --system
```

The installer builds an isolated environment, installs the API/WebUI, creates a persistent data directory, generates an admin token if one is not already configured, and registers/starts a service when systemd or OpenRC is available. SQLite data is kept outside the application directory, so upgrades/reinstalls do not delete the database.

For a per-user installation without a system service:

```sh
sh installer/install.sh --user
```

The installer checks system prerequisites and attempts to install missing Python/pip/venv packages automatically using the detected package manager: apt (Debian/Ubuntu), apk (Alpine/postmarketOS), dnf/yum (Fedora-family), pacman (Arch), or zypper (openSUSE). If needed, it uses sudo to request privilege escalation. Internet access and working distro package repositories are required. It verifies Python 3.10+ and venv before continuing. If configured repositories only offer an older Python, it stops with a clear error rather than installing an incompatible runtime. Set M_GROUP_PYTHON to a Python 3.10+ executable if it is not named python3.

## Access

By default the service binds to `127.0.0.1:8011` to avoid exposing member/financial data directly to the internet. For a VPS, use a TLS reverse proxy (recommended) or an SSH tunnel. For an SSH tunnel, run this from your own computer:

```sh
ssh -L 8011:127.0.0.1:8011 user@YOUR_VPS
```

Then open `http://127.0.0.1:8011` locally.

To intentionally serve a trusted LAN, set `M_GROUP_HOST=0.0.0.0` and configure firewall rules before restarting the service. Do not expose the raw API port publicly without HTTPS and appropriate network controls.

System install configuration and the generated admin token are stored in `/etc/m-group/m-group.env` with restrictive permissions. Keep this file secret. Change `M_GROUP_HOST` or `M_GROUP_PORT` there and restart the service:

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
