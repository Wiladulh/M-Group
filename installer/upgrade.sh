#!/bin/sh
set -eu
PREFIX=${M_GROUP_PREFIX:-/opt/M-Group}
"$PREFIX/venv/bin/pip" install --upgrade "$PWD"
