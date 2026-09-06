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

if ! command -v docker >/dev/null 2>&1; then
  echo "未找到 docker。请先安装 Docker 后再运行。" >&2
  exit 1
fi
if ! command -v hermes >/dev/null 2>&1; then
  echo "未找到 hermes。请先按官方文档安装 Hermes 0.20.x。" >&2
  exit 1
fi

"$PYTHON" scripts/setup_hermes_client.py --install-profile --start
echo "操作页 http://127.0.0.1:8765/operator"
echo "一键研究 http://127.0.0.1:8765"
echo "MCP http://127.0.0.1:8766/mcp"
echo "正在启动 Amazon Selector 客户端……"
exec hermes -p amazon-selector-client chat
