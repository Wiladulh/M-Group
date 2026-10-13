#!/bin/sh
set -eu
PREFIX=${M_GROUP_PREFIX:-/opt/M-Group}
rm -rf "$PREFIX"
echo "M-Group application removed; instance data preserved."
