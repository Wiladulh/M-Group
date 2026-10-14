#!/bin/sh
set -eu
usage() {
  cat <<'EOF'
M-Group Linux installer
Usage: sh installer/install.sh [--system|--user]
  --system  Install in /opt/M-Group and register systemd/OpenRC when available (root).
  --user    Install in ~/.local/lib/M-Group without a system service.
Environment: M_GROUP_PREFIX, M_GROUP_DATA_DIR, M_GROUP_CONFIG_DIR, M_GROUP_HOST,
M_GROUP_PORT, M_GROUP_ADMIN_TOKEN, M_GROUP_PYTHON, M_GROUP_SKIP_SERVICE=1.
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
# Bootstrap OS prerequisites before creating the virtual environment.
as_root() {
  if [ "$(id -u)" -eq 0 ]; then "$@"
  elif command -v sudo >/dev/null 2>&1; then sudo "$@"
  else echo "Missing system requirements. Re-run with root access or install them manually." >&2; return 1
  fi
}
python_ok() {
  command -v "$PYTHON" >/dev/null 2>&1 || return 1
  "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1 || return 1
  "$PYTHON" -m venv --help >/dev/null 2>&1 || return 1
}
if ! python_ok; then
  if command -v apt-get >/dev/null 2>&1; then
    echo "Installing Python/venv prerequisites with apt..."
    as_root apt-get update
    as_root apt-get install -y python3 python3-venv python3-pip ca-certificates
  elif command -v apk >/dev/null 2>&1; then
    echo "Installing Python/venv prerequisites with apk..."
    as_root apk add --no-cache python3 py3-pip py3-virtualenv ca-certificates
  elif command -v dnf >/dev/null 2>&1; then
    echo "Installing Python/venv prerequisites with dnf..."
    as_root dnf install -y python3 python3-pip ca-certificates
  elif command -v yum >/dev/null 2>&1; then
    echo "Installing Python/venv prerequisites with yum..."
    as_root yum install -y python3 python3-pip ca-certificates
  elif command -v pacman >/dev/null 2>&1; then
    echo "Installing Python/venv prerequisites with pacman..."
    as_root pacman -Sy --needed --noconfirm python python-pip ca-certificates
  elif command -v zypper >/dev/null 2>&1; then
    echo "Installing Python/venv prerequisites with zypper..."
    as_root zypper --non-interactive install python3 python3-pip ca-certificates
  else
    echo "Cannot auto-install prerequisites: unsupported package manager." >&2
    echo "Install Python 3.10+, pip, and venv support, then rerun this installer." >&2
    exit 1
  fi
fi
command -v "$PYTHON" >/dev/null 2>&1 || {
  echo "Python 3 was not found after prerequisite installation. Set M_GROUP_PYTHON to a Python 3.10+ executable." >&2
  exit 1
}
"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Installed Python is older than 3.10. Install Python 3.10+ from a supported repository and set M_GROUP_PYTHON if needed.")
PY
"$PYTHON" -m venv --help >/dev/null 2>&1 || {
  echo "Python venv is still unavailable after installing prerequisites. Check your distro's Python venv package." >&2
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
CONFIG_DIR=${M_GROUP_CONFIG_DIR:-/etc/m-group}
HOST=${M_GROUP_HOST:-0.0.0.0}
PORT=${M_GROUP_PORT:-8011}
ADMIN_TOKEN=${M_GROUP_ADMIN_TOKEN:-}
OPERATOR_PIN=${M_GROUP_CASHIER_OPERATOR_PIN:-}
# Interactive setup for headless/server installs. Defaults are persistent paths.
if [ "$MODE" = system ] && [ -t 0 ]; then
  printf "\nM-Group server setup (press Enter to accept the default)\n"
  printf "Listen address [0.0.0.0]: "
  IFS= read -r answer || answer=
  [ -z "$answer" ] || HOST=$answer
  printf "WebUI/API port [%s]: " "$PORT"
  IFS= read -r answer || answer=
  [ -z "$answer" ] || PORT=$answer
  printf "Application install directory [%s]: " "$PREFIX"
  IFS= read -r answer || answer=
  [ -z "$answer" ] || PREFIX=$answer
  printf "Persistent data/database directory [%s]: " "$DATA"
  IFS= read -r answer || answer=
  [ -z "$answer" ] || DATA=$answer
  printf "Configuration directory [%s]: " "$CONFIG_DIR"
  IFS= read -r answer || answer=
  [ -z "$answer" ] || CONFIG_DIR=$answer
  if [ -z "$ADMIN_TOKEN" ]; then
    printf "Admin API token (hidden; blank generates one automatically): "
    if stty -echo 2>/dev/null; then
      IFS= read -r ADMIN_TOKEN || ADMIN_TOKEN=
      stty echo 2>/dev/null || true
      printf "\n"
    else
      IFS= read -r ADMIN_TOKEN || ADMIN_TOKEN=
    fi
  fi
  if [ -z "$OPERATOR_PIN" ]; then
    printf "Initial Cashier operator PIN (4-6 digits; blank lets you set it later in WebUI, hidden): "
    if stty -echo 2>/dev/null; then
      IFS= read -r OPERATOR_PIN || OPERATOR_PIN=
      stty echo 2>/dev/null || true
      printf "\n"
    else
      IFS= read -r OPERATOR_PIN || OPERATOR_PIN=
    fi
  fi
fi
case "$HOST" in ""|*[!A-Za-z0-9.:_-]*) echo "M_GROUP_HOST must be an IP address or hostname (use 0.0.0.0 for all interfaces)." >&2; exit 2 ;; esac
case "$PORT" in ""|*[!0-9]*) echo "M_GROUP_PORT must be a TCP port number." >&2; exit 2 ;; esac
[ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || { echo "M_GROUP_PORT must be 1..65535." >&2; exit 2; }
for path_value in "$PREFIX" "$DATA" "$CONFIG_DIR"; do
  case "$path_value" in *[!A-Za-z0-9_./-]*)
    echo "Install, data, and config paths must not contain whitespace or shell-special characters." >&2
    exit 2
  esac
done
if [ -n "$ADMIN_TOKEN" ]; then
  case "$ADMIN_TOKEN" in *[!A-Za-z0-9._~-]*) echo "Admin token may contain only letters, numbers, dot, underscore, tilde, and hyphen." >&2; exit 2 ;; esac
  [ "${#ADMIN_TOKEN}" -ge 24 ] || { echo "Admin token must be at least 24 characters." >&2; exit 2; }
fi
if [ -n "$OPERATOR_PIN" ]; then
  case "$OPERATOR_PIN" in *[!0-9]*) echo "Cashier operator PIN must contain digits only." >&2; exit 2 ;; esac
  [ "${#OPERATOR_PIN}" -ge 4 ] && [ "${#OPERATOR_PIN}" -le 6 ] || { echo "Cashier operator PIN must be 4-6 digits." >&2; exit 2; }
fi
case "$PORT" in ''|*[!0-9]*) echo "M_GROUP_PORT must be a TCP port number." >&2; exit 2 ;; esac
[ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || { echo "M_GROUP_PORT must be 1..65535." >&2; exit 2; }
mkdir -p "$PREFIX" "$DATA" "$BIN_DIR"
chmod 0700 "$DATA"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install "$SOURCE_DIR"
cat > "$BIN_DIR/m-group" <<EOF
#!/bin/sh
umask 077
export M_GROUP_DATA_DIR="$DATA"
exec "$VENV/bin/m-group" "\$@"
EOF
chmod 0755 "$BIN_DIR/m-group"
if [ "$MODE" = system ]; then
  cat > "$BIN_DIR/m-group-server" <<EOF
#!/bin/sh
set -eu
umask 077
if [ -r "$CONFIG_DIR/m-group.env" ]; then
  set -a
  . "$CONFIG_DIR/m-group.env"
  set +a
fi
export M_GROUP_DATA_DIR="$DATA"
export M_GROUP_HOST="\${M_GROUP_HOST:-$HOST}"
export M_GROUP_PORT="\${M_GROUP_PORT:-$PORT}"
exec "$VENV/bin/uvicorn" app.main:app --host "\$M_GROUP_HOST" --port "\$M_GROUP_PORT"
EOF
else
  cat > "$BIN_DIR/m-group-server" <<EOF
#!/bin/sh
set -eu
umask 077
export M_GROUP_DATA_DIR="$DATA"
export M_GROUP_HOST="\${M_GROUP_HOST:-$HOST}"
export M_GROUP_PORT="\${M_GROUP_PORT:-$PORT}"
exec "$VENV/bin/uvicorn" app.main:app --host "\$M_GROUP_HOST" --port "\$M_GROUP_PORT"
EOF
fi
chmod 0755 "$BIN_DIR/m-group-server"
if [ "$MODE" = system ]; then
  ENV_FILE="$CONFIG_DIR/m-group.env"
  mkdir -p "$CONFIG_DIR"
  if [ -z "$ADMIN_TOKEN" ] && [ -f "$ENV_FILE" ]; then
    ADMIN_TOKEN=$(sed -n 's/^M_GROUP_ADMIN_TOKEN=//p' "$ENV_FILE" | head -n 1)
  fi
  GENERATED_TOKEN=0
  if [ -z "$ADMIN_TOKEN" ]; then ADMIN_TOKEN=$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(40))'); GENERATED_TOKEN=1; fi
  umask 077
  cat > "$ENV_FILE" <<EOF
M_GROUP_HOST=$HOST
M_GROUP_PORT=$PORT
M_GROUP_DATA_DIR=$DATA
M_GROUP_DB_PATH=$DATA/M-Group.db
M_GROUP_ADMIN_TOKEN=$ADMIN_TOKEN
EOF
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
  chmod 0750 "$DATA"
  # OpenRC starts the wrapper as SERVICE_USER, so its environment file must be
  # readable by that account without exposing the token to other local users.
  chown root:"$SERVICE_USER" "$CONFIG_DIR"
  chmod 0750 "$CONFIG_DIR"
  chown root:"$SERVICE_USER" "$ENV_FILE"
  chmod 0640 "$ENV_FILE"
  cat > "$BIN_DIR/m-group-server-openrc" <<EOF
#!/bin/sh
set -eu
set -a
. "$ENV_FILE"
set +a
exec "$BIN_DIR/m-group-server"
EOF
  chmod 0755 "$BIN_DIR/m-group-server-openrc"
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
    touch /var/log/m-group.log
    chown "$SERVICE_USER:$SERVICE_USER" /var/log/m-group.log
    chmod 0640 /var/log/m-group.log
    cat > /etc/init.d/m-group <<EOF
#!/sbin/openrc-run
name="M-Group"
description="M-Group server"
command="$BIN_DIR/m-group-server-openrc"
command_user="$SERVICE_USER:$SERVICE_USER"
command_background="yes"
pidfile="/run/m-group.pid"
output_log="/var/log/m-group.log"
error_log="/var/log/m-group.log"
directory="$PREFIX"
depend() { need net; after firewall; }
EOF
    chmod 0755 /etc/init.d/m-group
    rc-update add m-group default
    rc-service m-group start
    echo "OpenRC service enabled and started."
  else
    echo "No active systemd/OpenRC detected; service was not registered."
  fi
  echo "Configuration stored in $ENV_FILE (permissions 0640, readable only by root and the service group); keep it secret."
  if [ "$GENERATED_TOKEN" = 1 ]; then echo "Generated admin token (save it now): $ADMIN_TOKEN"; fi
fi
echo "M-Group installed successfully."
echo "Install prefix: $PREFIX"
echo "Data directory: $DATA"
echo "Server: $BIN_DIR/m-group-server"
echo "WebUI/API port: $PORT"
if [ "$HOST" = 0.0.0.0 ]; then echo "Listening on all interfaces. Ensure firewall/NAT rules and HTTPS/reverse proxy are configured before public production use."; fi
