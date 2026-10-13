#!/bin/sh
set -eu
PREFIX=${M_GROUP_PREFIX:-/opt/M-Group}
if [ "$(id -u)" -ne 0 ] && [ "$PREFIX" = /opt/M-Group ]; then
  echo "System uninstall requires root." >&2
  exit 1
fi
if command -v systemctl >/dev/null 2>&1; then
  systemctl disable --now m-group.service 2>/dev/null || true
  rm -f /etc/systemd/system/m-group.service
  systemctl daemon-reload 2>/dev/null || true
fi
if command -v rc-service >/dev/null 2>&1; then
  rc-service m-group stop 2>/dev/null || true
  rc-update del m-group default 2>/dev/null || true
  rm -f /etc/init.d/m-group
fi
rm -rf "$PREFIX"
echo "M-Group application removed; database and configuration were preserved."
