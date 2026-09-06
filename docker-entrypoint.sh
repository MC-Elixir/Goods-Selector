#!/bin/sh
set -e

DATA_DIR="${AMAZON_SELECTOR_DATA_DIR:-/app/data}"
export LOG_DIR="${LOG_DIR:-$DATA_DIR/logs}"
mkdir -p "$DATA_DIR/cache" "$DATA_DIR/exports" "$DATA_DIR/images" "$DATA_DIR/logs"

# Idempotent: create_all is a no-op when tables already exist.
python main.py init-db || echo "[entrypoint] init-db failed, continuing" >&2

case "$1" in
  init-db|run|smoke-run|seller-sprite-check|seller-sprite-asin-check|seller-sprite-configure|alibaba-pifatuan-check|agent-web|selector-mcp)
    exec python main.py "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
