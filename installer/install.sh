#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PYTHON=${M_GROUP_PYTHON:-python3}
MIN_CORES=2
MIN_RAM_KB=$((315 * 1024))

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3.10+ is required."
  exit 1
fi

"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ is required.")
PY

CORES=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 0)
RAM_KB=$(awk '/MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)

if [ "$CORES" -lt "$MIN_CORES" ]; then
  echo "M_GROUP requires at least ${MIN_CORES} CPU cores; detected ${CORES}."
  exit 1
fi

if [ "$RAM_KB" -lt "$MIN_RAM_KB" ]; then
  echo "M_GROUP requires at least 315 MB RAM; detected ${RAM_KB} KB."
  exit 1
fi

if [ "$(id -u)" -eq 0 ]; then
  PREFIX=${M_GROUP_PREFIX:-/opt/M_GROUP}
  DATA=${M_GROUP_DATA_DIR:-/var/lib/M_GROUP}
else
  PREFIX=${M_GROUP_PREFIX:-"$HOME/.local/lib/M_GROUP"}
  DATA=${M_GROUP_DATA_DIR:-"$HOME/.local/share/M_GROUP"}
fi

mkdir -p "$PREFIX" "$DATA"
"$PYTHON" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/python" -m pip install --upgrade pip
"$PREFIX/venv/bin/python" -m pip install "$SOURCE_DIR"

mkdir -p "$PREFIX/bin"

cat > "$PREFIX/bin/M_GROUP" <<EOF
#!/bin/sh
export M_GROUP_DATA_DIR="$DATA"
exec "$PREFIX/venv/bin/M_GROUP" "\\$@"
EOF
chmod 0755 "$PREFIX/bin/M_GROUP"

cat > "$PREFIX/bin/M_GROUP-server" <<EOF
#!/bin/sh
set -eu
export M_GROUP_DATA_DIR="$DATA"
exec "$PREFIX/venv/bin/uvicorn" app.main:app --host "\\${M_GROUP_HOST:-127.0.0.1}" --port "\\${M_GROUP_PORT:-8011}"
EOF
chmod 0755 "$PREFIX/bin/M_GROUP-server"

echo "M_GROUP installed successfully."
echo "Install prefix: $PREFIX"
echo "Data directory: $DATA"
echo "Server: $PREFIX/bin/M_GROUP-server"
echo "CLI: $PREFIX/bin/M_GROUP"
echo "For LAN/ESP32 access: M_GROUP_HOST=0.0.0.0"
echo "For device provisioning: set M_GROUP_ADMIN_TOKEN"
