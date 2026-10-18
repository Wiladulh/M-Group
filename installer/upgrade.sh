#!/bin/sh
set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
CONFIG_DIR=${M_GROUP_CONFIG_DIR:-/etc/m-group}
PREFIX_OVERRIDE=${M_GROUP_PREFIX:-}
DATA_OVERRIDE=${M_GROUP_DATA_DIR:-}
DB_OVERRIDE=${M_GROUP_DB_PATH:-}

# Read only the installer's simple KEY=value settings; never source this file.
read_config_value() {
  key=$1
  [ -r "$CONFIG_DIR/m-group.env" ] || return 0
  sed -n "s/^${key}=//p" "$CONFIG_DIR/m-group.env" | head -n 1
}
CONFIG_PREFIX=$(read_config_value M_GROUP_PREFIX)
CONFIG_DATA=$(read_config_value M_GROUP_DATA_DIR)
CONFIG_DB=$(read_config_value M_GROUP_DB_PATH)
PREFIX=${PREFIX_OVERRIDE:-${CONFIG_PREFIX:-/opt/M-Group}}
DATA=${DATA_OVERRIDE:-${CONFIG_DATA:-/var/lib/M-Group}}
DB_PATH=${DB_OVERRIDE:-${CONFIG_DB:-"$DATA/M-Group.db"}}
PYTHON="$PREFIX/venv/bin/python"
[ -x "$PYTHON" ] || { echo "M-Group Python environment not found at $PYTHON." >&2; exit 1; }
[ -d "$SOURCE_DIR/app" ] || { echo "Application source not found at $SOURCE_DIR/app." >&2; exit 1; }
[ -f "$DB_PATH" ] || { echo "Database not found at $DB_PATH; refusing to upgrade without a verified pre-upgrade snapshot." >&2; exit 1; }

# Preserve the original service state. Never start a service that was stopped.
MANAGER=none
WAS_ACTIVE=0
if command -v systemctl >/dev/null 2>&1 && systemctl cat m-group >/dev/null 2>&1; then
  MANAGER=systemd
  if systemctl is-active --quiet m-group; then WAS_ACTIVE=1; fi
elif command -v rc-service >/dev/null 2>&1; then
  MANAGER=openrc
  if rc-service m-group status >/dev/null 2>&1; then WAS_ACTIVE=1; fi
fi

# Keep backups private from the moment they are created.
mkdir -p "$DATA/backups"
chmod 0700 "$DATA/backups"
BACKUP="$DATA/backups/M-Group_PRE_UPGRADE_$(date +%Y%m%d_%H%M%S)_$$.sqlite3"
"$PYTHON" - "$DB_PATH" "$BACKUP" <<'PY'
import os, sqlite3, sys
source_path, backup_path = sys.argv[1:3]
source = sqlite3.connect("file:" + source_path + "?mode=ro", uri=True, timeout=30)
target = None
try:
    target = sqlite3.connect(backup_path)
    source.backup(target)
    target.commit()
    result = target.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise RuntimeError("Pre-upgrade backup integrity_check failed: " + str(result))
finally:
    source.close()
    if target is not None:
        target.close()
os.chmod(backup_path, 0o600)
PY
echo "Verified pre-upgrade database backup: $BACKUP"

# Configure the new WebUI login only after a verified pre-upgrade backup exists.
sh "$SCRIPT_DIR/configure-admin-login.sh" "$CONFIG_DIR/m-group.env" "$PYTHON"

# Stop an active instance before replacing package files. On failure it remains
# stopped so an unverified or partially upgraded API is not exposed.
if [ "$WAS_ACTIVE" -eq 1 ]; then
  case "$MANAGER" in
    systemd) systemctl stop m-group ;;
    openrc) rc-service m-group stop ;;
  esac
fi

"$PYTHON" -m pip install --upgrade "$SOURCE_DIR"
"$PYTHON" -m compileall -q "$SOURCE_DIR/app"
"$PYTHON" -c 'import app.api.routes; print("API module import check: OK")'

# Do not change a deliberately stopped service into a running service.
if [ "$WAS_ACTIVE" -eq 0 ]; then
  echo "Upgrade files validated. Service was stopped before upgrade and remains stopped."
  echo "Run the controlled API security smoke test before enabling M-Group."
  exit 0
fi

case "$MANAGER" in
  systemd) systemctl start m-group ;;
  openrc) rc-service m-group start ;;
  *) echo "Cannot safely restore prior active state: no supported service manager." >&2; exit 1 ;;
esac

# A successful process start is not enough: health must respond and sensitive
# dashboard data must remain protected without the admin token.
PORT=$(read_config_value M_GROUP_PORT)
PORT=${PORT:-8011}
if ! "$PYTHON" - "$PORT" <<'PY'
import http.client, sys, time
port = int(sys.argv[1])
last_error = None
for attempt in range(20):
    conn = None
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/api/v1/health")
        health = conn.getresponse()
        health.read()
        if health.status != 200:
            raise RuntimeError("health endpoint returned HTTP " + str(health.status))
        conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/api/v1/dashboard")
        dashboard = conn.getresponse()
        dashboard.read()
        if dashboard.status != 401:
            raise RuntimeError("unauthenticated dashboard returned HTTP " + str(dashboard.status) + "; expected 401")
        print("API smoke test: health=200, unauthenticated dashboard=401")
        break
    except Exception as exc:
        last_error = exc
        time.sleep(1)
    finally:
        if conn is not None:
            conn.close()
else:
    raise SystemExit("API smoke test failed: " + str(last_error))
PY
then
  echo "API security smoke test failed; stopping M-Group to avoid exposing an unverified service." >&2
  case "$MANAGER" in
    systemd) systemctl stop m-group || true ;;
    openrc) rc-service m-group stop || true ;;
  esac
  exit 1
fi
echo "Upgrade complete; prior service state restored and API security smoke test passed."
