#!/bin/sh
# Dedicated installer for the clean-room M-Group v2 runtime.
# Run from a checked-out repository: sudo sh rebuild-v2/ops/install-v2.sh
set -eu

usage() {
  cat <<'EOF'
M-Group clean-room v2 installer (systemd)
Usage: sudo sh rebuild-v2/ops/install-v2.sh [--no-service]
Optional environment:
  MGROUP_V2_PREFIX       Install root (default /opt/M-Group-v2)
  MGROUP_V2_DATA_DIR     Persistent data (default /var/lib/M-Group-v2)
  MGROUP_V2_CONFIG_DIR   Secret config (default /etc/m-group-v2)
  MGROUP_V2_HOST         Bind address (default 127.0.0.1)
  MGROUP_V2_PORT         Port (default 8080)
  MGROUP_ADMIN_USERNAME  Initial admin username (default admin)
  MGROUP_ADMIN_PASSWORD  Initial admin password (generated if omitted)
  MGROUP_DEVICE_KEY_PEPPER  Stable secret (generated on first install if omitted)
Use --no-service to install files without registering/starting systemd.
This installer does not migrate or modify the legacy M-Group installation.
EOF
}
NO_SERVICE=0
case "${1:-}" in
  "") ;;
  --no-service) NO_SERVICE=1 ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo)." >&2; exit 1; }
if [ "$NO_SERVICE" -eq 0 ]; then
  command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ] || {
    echo "An active systemd system is required; use --no-service only for staging." >&2
    exit 1
  }
fi
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
V2_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
[ -d "$V2_DIR/backend/mgroup_backend" ] || { echo "Cannot find rebuild-v2/backend/mgroup_backend." >&2; exit 1; }
[ -d "$V2_DIR/webui" ] || { echo "Cannot find rebuild-v2/webui." >&2; exit 1; }

PYTHON=${MGROUP_V2_PYTHON:-python3}
command -v "$PYTHON" >/dev/null 2>&1 || { echo "Python 3.12+ is required." >&2; exit 1; }
"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit("M-Group v2 requires Python 3.12 or newer.")
PY
"$PYTHON" -m venv --help >/dev/null 2>&1 || {
  echo "Python venv support is missing (install python3-venv for your distro)." >&2
  exit 1
}

PREFIX=${MGROUP_V2_PREFIX:-/opt/M-Group-v2}
DATA=${MGROUP_V2_DATA_DIR:-/var/lib/M-Group-v2}
CONFIG=${MGROUP_V2_CONFIG_DIR:-/etc/m-group-v2}
HOST=${MGROUP_V2_HOST:-127.0.0.1}
PORT=${MGROUP_V2_PORT:-8080}
case "$PORT" in ''|*[!0-9]*) echo "MGROUP_V2_PORT must be a TCP port number." >&2; exit 2 ;; esac
[ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || { echo "MGROUP_V2_PORT must be 1..65535." >&2; exit 2; }
case "$HOST" in *[!A-Za-z0-9.:_-]*) echo "Invalid MGROUP_V2_HOST." >&2; exit 2 ;; esac
case "$PREFIX$DATA$CONFIG" in *[!A-Za-z0-9._/-]*) echo "Install, data and config paths may contain only letters, numbers, dot, underscore, slash and hyphen." >&2; exit 2 ;; esac

SERVICE_USER=m-group-v2
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  if command -v useradd >/dev/null 2>&1; then
    useradd --system --home-dir "$DATA" --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
  else
    echo "useradd is required to create the restricted service account." >&2
    exit 1
  fi
fi

STAMP=$(date -u +%Y%m%dT%H%M%SZ)-$(date +%s)
RELEASE="$PREFIX/releases/$STAMP"
mkdir -p "$RELEASE/backend" "$RELEASE/webui" "$PREFIX/releases" "$DATA" "$CONFIG"
cp -R "$V2_DIR/backend/." "$RELEASE/backend/"
cp -R "$V2_DIR/webui/." "$RELEASE/webui/"
"$PYTHON" -m venv "$RELEASE/venv"
"$RELEASE/venv/bin/python" -m pip install --upgrade pip
"$RELEASE/venv/bin/python" -m pip install -r "$RELEASE/backend/requirements.txt"

ENV_FILE="$CONFIG/mgroup-v2.env"
if [ ! -f "$ENV_FILE" ]; then
  ADMIN_USER=${MGROUP_ADMIN_USERNAME:-admin}
  ADMIN_PASS=${MGROUP_ADMIN_PASSWORD:-$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(24))')}
  PEPPER=${MGROUP_DEVICE_KEY_PEPPER:-$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(48))')}
  "$PYTHON" - "$ADMIN_USER" "$ADMIN_PASS" "$PEPPER" <<'PY'
import re, sys
username, password, pepper = sys.argv[1:]
if not re.fullmatch(r"[a-zA-Z0-9_.-]{3,64}", username):
    raise SystemExit("MGROUP_ADMIN_USERNAME must be 3-64 characters: letters, numbers, dot, underscore or hyphen.")
if not 12 <= len(password) <= 128 or any(c in password for c in "\r\n"):
    raise SystemExit("MGROUP_ADMIN_PASSWORD must be 12-128 characters and contain no newline.")
if len(pepper) < 32 or any(c in pepper for c in "\r\n"):
    raise SystemExit("MGROUP_DEVICE_KEY_PEPPER must be at least 32 characters and contain no newline.")
PY
  umask 077
  {
    printf 'MGROUP_ADMIN_USERNAME=%s\n' "$ADMIN_USER"
    printf 'MGROUP_ADMIN_PASSWORD=%s\n' "$ADMIN_PASS"
    printf 'MGROUP_DEVICE_KEY_PEPPER=%s\n' "$PEPPER"
    printf 'MGROUP_DB_PATH=%s/mgroup-v2.sqlite3\n' "$DATA"
  } > "$ENV_FILE"
  chmod 0600 "$ENV_FILE"
  if [ -z "${MGROUP_ADMIN_PASSWORD:-}" ]; then
    echo "INITIAL ADMIN CREDENTIALS (save securely; shown only on first install):"
    echo "Username: $ADMIN_USER"
    echo "Password: $ADMIN_PASS"
  fi
else
  echo "Existing v2 environment file preserved: $ENV_FILE"
fi

chown -R root:root "$PREFIX"
chmod -R go-w "$PREFIX"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA"
chown root:"$SERVICE_USER" "$CONFIG"
chmod 0750 "$CONFIG"
chmod 0640 "$ENV_FILE"

ln -sfn "$RELEASE" "$PREFIX/current"
cat > "$PREFIX/mgroup-v2-server" <<EOF
#!/bin/sh
set -eu
set -a
. "$ENV_FILE"
set +a
export PYTHONPATH="$PREFIX/current/backend"
exec "$PREFIX/current/venv/bin/uvicorn" mgroup_backend.main:app --host "$HOST" --port "$PORT" --proxy-headers --forwarded-allow-ips=127.0.0.1
EOF
chmod 0755 "$PREFIX/mgroup-v2-server"

if [ "$NO_SERVICE" -eq 0 ]; then
  cat > /etc/systemd/system/m-group-v2.service <<EOF
[Unit]
Description=M-Group clean-room v2 server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$PREFIX/current
EnvironmentFile=$ENV_FILE
ExecStart=$PREFIX/mgroup-v2-server
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=$DATA
RestrictSUIDSGID=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now m-group-v2.service
  echo "systemd service enabled and started: m-group-v2.service"
else
  echo "Files installed; service was not registered or started (--no-service)."
fi

echo "M-Group v2 installation complete."
echo "Release: $RELEASE"
echo "WebUI/API: http://$HOST:$PORT/"
echo "Health: http://$HOST:$PORT/api/v2/health"
echo "Persistent data: $DATA"
echo "Secrets: $ENV_FILE (root and $SERVICE_USER readable only)"
if [ "$HOST" = "127.0.0.1" ]; then
  echo "Bound to localhost; put a TLS reverse proxy in front before remote access."
fi
echo "Legacy installer and legacy app runtime were not changed."
