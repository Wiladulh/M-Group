#!/bin/sh
set -eu
umask 077

CONFIG_FILE=${1:?usage: configure-admin-login.sh CONFIG_FILE PYTHON}
PYTHON=${2:?usage: configure-admin-login.sh CONFIG_FILE PYTHON}
[ -x "$PYTHON" ] || { echo "Python executable not found: $PYTHON" >&2; exit 1; }
mkdir -p "$(dirname "$CONFIG_FILE")"
[ -f "$CONFIG_FILE" ] || : > "$CONFIG_FILE"

read_config() {
  key=$1
  value=$(sed -n "s/^$key=//p" "$CONFIG_FILE" | head -n 1)
  value=${value#\'}
  value=${value%\'}
  printf '%s' "$value"
}
# The primary WebUI account name is fixed by the product contract.
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=${M_GROUP_ADMIN_PASSWORD_HASH:-$(read_config M_GROUP_ADMIN_PASSWORD_HASH)}

if [ -z "$ADMIN_PASSWORD_HASH" ]; then
  if [ ! -t 0 ]; then
    echo "WebUI login password hash is missing. Set M_GROUP_ADMIN_PASSWORD_HASH or rerun interactively." >&2
    exit 2
  fi
  printf "WebUI admin password (hidden): "
  if stty -echo 2>/dev/null; then
    IFS= read -r ADMIN_PASSWORD || ADMIN_PASSWORD=
    stty echo 2>/dev/null || true
    printf "\n"
  else
    IFS= read -r ADMIN_PASSWORD || ADMIN_PASSWORD=
  fi
  printf "Confirm WebUI admin password (hidden): "
  if stty -echo 2>/dev/null; then
    IFS= read -r ADMIN_PASSWORD_CONFIRM || ADMIN_PASSWORD_CONFIRM=
    stty echo 2>/dev/null || true
    printf "\n"
  else
    IFS= read -r ADMIN_PASSWORD_CONFIRM || ADMIN_PASSWORD_CONFIRM=
  fi
  [ -n "$ADMIN_PASSWORD" ] && [ "$ADMIN_PASSWORD" = "$ADMIN_PASSWORD_CONFIRM" ] || {
    unset ADMIN_PASSWORD ADMIN_PASSWORD_CONFIRM
    echo "Password is empty or confirmation does not match." >&2
    exit 2
  }
  ADMIN_PASSWORD_HASH=$(printf '%s' "$ADMIN_PASSWORD" | "$PYTHON" -c '
import hashlib, secrets, sys
password = sys.stdin.buffer.read()
salt = secrets.token_bytes(16)
iterations = 310000
digest = hashlib.pbkdf2_hmac("sha256", password, salt, iterations)
print("pbkdf2_sha256$%d$%s$%s" % (iterations, salt.hex(), digest.hex()))
')
  unset ADMIN_PASSWORD ADMIN_PASSWORD_CONFIRM
fi
case "$ADMIN_PASSWORD_HASH" in
  pbkdf2_sha256\$*) ;;
  *) echo "M_GROUP_ADMIN_PASSWORD_HASH must be a pbkdf2_sha256 hash. Generate it with 'm-group hash-password'." >&2; exit 2 ;;
esac

DIR=$(dirname "$CONFIG_FILE")
TMP="$DIR/.m-group.env.$$"
GROUP=$(stat -c %G "$CONFIG_FILE" 2>/dev/null || echo root)
awk -F= '$1 != "M_GROUP_ADMIN_USERNAME" && $1 != "M_GROUP_ADMIN_PASSWORD_HASH" && $1 != "M_GROUP_ADMIN_TOKEN" { print }' "$CONFIG_FILE" > "$TMP"
printf "M_GROUP_ADMIN_USERNAME=%s\nM_GROUP_ADMIN_PASSWORD_HASH='%s'\n" "$ADMIN_USERNAME" "$ADMIN_PASSWORD_HASH" >> "$TMP"
chmod 0640 "$TMP"
if [ "$(id -u)" -eq 0 ] && command -v chown >/dev/null 2>&1; then
  chown "root:$GROUP" "$TMP" 2>/dev/null || true
fi
mv "$TMP" "$CONFIG_FILE"
echo "WebUI username/password configuration saved."
