#!/bin/sh
set -eu
PREFIX=${M_GROUP_PREFIX:-/opt/M_GROUP}
rm -rf "$PREFIX"
echo "M_GROUP application removed; instance data preserved."
