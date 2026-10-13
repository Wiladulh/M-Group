#!/bin/sh
set -eu
usage() {
  cat <<'EOF'
M-Group Linux installer
Usage: sh installer/install.sh [--system|--user]
  --system  Install in /opt/M-Group and register systemd/OpenRC when available (root).
  --user    Install in ~/.local/lib/M-Group without a system service.
Environment: M_GROUP_PREFIX, M_GROUP_DATA_DIR, M_GROUP_HOST, M_GROUP_PORT,
M_GROUP_ADMIN_TOKEN, M_GROUP_PYTHON, M_GROUP_SKIP_SERVICE=1.
EOF
}
MODE=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --system) MODE=system ;;
    --user) MODE=user ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PYTHON=${M_GROUP_PYTHON:-python3}
if [ -z "$MODE" ]; then
  if [ "$(id -u)" -eq 0 ]; then MODE=system; else MODE=user; fi
fi
if [ "$MODE" = system ] && [ "$(id -u)" -ne 0 ]; then
  echo "--system requires root; use sudo sh installer/install.sh --system." >&2
  exit 1
fi
command -v "$PYTHON" >/dev/null 2>&1 || { echo "Python 3.10+ is required." >&2; exit 1; }
"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("M-Group requires Python 3.10 or newer.")
PY
"$PYTHON" -m venv --help >/dev/null 2>&1 || {
  echo "Python venv support is missing. Install your distro's venv package (e.g. python3-venv on Debian/Ubuntu)." >&2
  exit 1
}
if [ "$MODE" = system ]; then
  PREFIX=${M_GROUP_PREFIX:-/opt/M-Group}
  DATA=${M_GROUP_DATA_DIR:-/var/lib/M-Group}
else
  PREFIX=${M_GROUP_PREFIX:-"$HOME/.local/lib/M-Group"}
  DATA=${M_GROUP_DATA_DIR:-"$HOME/.local/share/M-Group"}
fi
VENV="$PREFIX/venv"
BIN_DIR="$PREFIX/bin"
HOST=${M_GROUP_HOST:-127.0.0.1}
PORT=${M_GROUP_PORT:-8011}
case "$PORT" in ''|*[!0-9]*) echo "M_GROUP_PORT must be a TCP port number." >&2; exit 2 ;; esac
[ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || { echo "M_GROUP_PORT must be 1..65535." >&2; exit 2; }
mkdir -p "$PREFIX" "$DATA" "$BIN_DIR"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install "$SOURCE_DIR"
cat > "$BIN_DIR/m-group" <<EOF
#!/bin/sh
export M_GROUP_DATA_DIR="$DATA"
exec "$VENV/bin/m-group" "\$@"
EOF
chmod 0755 "$BIN_DIR/m-group"
cat > "$BIN_DIR/m-group-server" <<EOF
#!/bin/sh
set -eu
export M_GROUP_DATA_DIR="$DATA"
export M_GROUP_HOST="\${M_GROUP_HOST:-$HOST}"
export M_GROUP_PORT="\${M_GROUP_PORT:-$PORT}"
exec "$VENV/bin/uvicorn" app.main:app --host "\$M_GROUP_HOST" --port "\$M_GROUP_PORT"
EOF
chmod 0755 "$BIN_DIR/m-group-server"
if [ "$MODE" = system ]; then
  CONFIG_DIR=${M_GROUP_CONFIG_DIR:-/etc/m-group}
  ENV_FILE="$CONFIG_DIR/m-group.env"
  mkdir -p "$CONFIG_DIR"
  ADMIN_TOKEN=${M_GROUP_ADMIN_TOKEN:-}
  if [ -z "$ADMIN_TOKEN" ] && [ -f "$ENV_FILE" ]; then
    ADMIN_TOKEN=$(sed -n 's/^M_GROUP_ADMIN_TOKEN=//p' "$ENV_FILE" | head -n 1)
  fi
  if [ -z "$ADMIN_TOKEN" ]; then ADMIN_TOKEN=$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(40))'); fi
  umask 077
  cat > "$ENV_FILE" <<EOF
M_GROUP_HOST=$HOST
M_GROUP_PORT=$PORT
M_GROUP_DATA_DIR=$DATA
M_GROUP_DB_PATH=$DATA/M-Group.db
M_GROUP_ADMIN_TOKEN=$ADMIN_TOKEN
EOF
  chmod 0600 "$ENV_FILE"
  SERVICE_USER=m-group
  if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    if command -v useradd >/dev/null 2>&1; then
      useradd --system --home-dir "$DATA" --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    elif command -v adduser >/dev/null 2>&1; then
      adduser -S -D -H -h "$DATA" -s /sbin/nologin "$SERVICE_USER"
    else
      SERVICE_USER=root
      echo "Warning: cannot create service user; service will run as root." >&2
    fi
  fi
  if [ "$SERVICE_USER" != root ]; then chown -R "$SERVICE_USER" "$DATA"; fi
  if [ "${M_GROUP_SKIP_SERVICE:-0}" != 1 ] && command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    cat > /etc/systemd/system/m-group.service <<EOF
[Unit]
Description=M-Group Server
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$PREFIX
EnvironmentFile=$ENV_FILE
ExecStart=$BIN_DIR/m-group-server
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now m-group.service
    echo "systemd service enabled and started."
  elif [ "${M_GROUP_SKIP_SERVICE:-0}" != 1 ] && command -v rc-update >/dev/null 2>&1 && [ -d /etc/init.d ]; then
    cat > /etc/init.d/m-group <<EOF
#!/sbin/openrc-run
name="M-Group"
description="M-Group server"
command="$BIN_DIR/m-group-server"
command_user="$SERVICE_USER:$SERVICE_USER"
command_background="yes"
pidfile="/run/m-group.pid"
output_log="/var/log/m-group.log"
error_log="/var/log/m-group.log"
directory="$PREFIX"
start_stop_daemon_args="--env-file $ENV_FILE"
depend() { need net; after firewall; }
EOF
    chmod 0755 /etc/init.d/m-group
    rc-update add m-group default
    rc-service m-group start
    echo "OpenRC service enabled and started."
  else
    echo "No active systemd/OpenRC detected; service was not registered."
  fi
  echo "Admin token stored in $ENV_FILE; keep it secret."
fi
echo "M-Group installed successfully."
echo "Install prefix: $PREFIX"
echo "Data directory: $DATA"
echo "Server: $BIN_DIR/m-group-server"
echo "WebUI/API port: $PORT"
if [ "$HOST" = 127.0.0.1 ]; then echo "Bound to localhost only; use SSH tunnel or configure a TLS reverse proxy."; fi
