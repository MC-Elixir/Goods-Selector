#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "未找到 python3/python，请先安装 Python 3。" >&2
  exit 1
fi

"$PYTHON" scripts/setup_hermes_client.py --install-profile --start
echo "正在启动 Amazon Selector 客户端……"
exec hermes -p amazon-selector-client chat
