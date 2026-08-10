#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"

python scripts/setup_hermes_client.py --install-profile --start
echo "正在启动 Amazon Selector 客户端……"
exec hermes -p amazon-selector-client chat
