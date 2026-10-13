#!/bin/sh
set -eu
exec python3 -m uvicorn app.main:app --host "${M_GROUP_HOST:-127.0.0.1}" --port "${M_GROUP_PORT:-8011}"
