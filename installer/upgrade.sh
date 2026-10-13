#!/bin/sh
set -eu
PREFIX=${M_GROUP_PREFIX:-/opt/M_GROUP}
"$PREFIX/venv/bin/pip" install --upgrade "$PWD"
