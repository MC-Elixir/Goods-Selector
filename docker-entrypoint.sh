#!/bin/sh
set -e
# Idempotent: create_all is a no-op when tables already exist.
python main.py init-db || echo "[entrypoint] init-db failed, continuing" >&2
exec python main.py "$@"
