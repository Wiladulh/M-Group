#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PREFIX=${M_GROUP_PREFIX:-/opt/M-Group}
[ -x "$PREFIX/venv/bin/python" ] || { echo "M-Group not found at $PREFIX." >&2; exit 1; }
"$PREFIX/venv/bin/python" -m pip install --upgrade "$SOURCE_DIR"
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet m-group; then
  systemctl restart m-group
elif command -v rc-service >/dev/null 2>&1 && rc-service m-group status >/dev/null 2>&1; then
  rc-service m-group restart
fi
echo "M-Group upgraded; instance data preserved."
