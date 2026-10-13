#!/bin/sh
set -eu
PREFIX=${M-Group_PREFIX:-/opt/M-Group}
rm -rf "$PREFIX"
echo "M-Group application removed; instance data preserved."
