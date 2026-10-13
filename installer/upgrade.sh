#!/bin/sh
set -eu
PREFIX=${M-Group_PREFIX:-/opt/M-Group}
"$PREFIX/venv/bin/pip" install --upgrade "$PWD"
