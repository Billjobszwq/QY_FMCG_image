#!/bin/bash
# 监控服务包装脚本（供 launchd 守护调用）
# launchd 会在进程退出时自动重启（KeepAlive），实现"永不挂"。
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1
PYTHON_BIN="${PYTHON_BIN:-python3}"
exec "$PYTHON_BIN" -m src.training.monitor --port 8092
