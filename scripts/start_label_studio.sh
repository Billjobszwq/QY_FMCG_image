#!/usr/bin/env bash
# Label Studio 启动脚本（本地原生，端口 8300）
# 启用旧版 token 认证以支持 API / ML 后端 token 访问。
set -e
cd "$(dirname "$0")/../.."
ROOT="$(pwd)"

export LABEL_STUDIO_BASE_DATA_DIR="$ROOT/.label-studio"
export LABEL_STUDIO_PORT=8300
export LABEL_STUDIO_ENABLE_LEGACY_TOKEN_AUTH=true
export LABEL_STUDIO_DISABLE_SIGNUP_WITHOUT_LINK=false
export DJANGO_DB=default

echo "启动 Label Studio: http://127.0.0.1:8300  (数据目录: $LABEL_STUDIO_BASE_DATA_DIR)"
exec python -m label_studio.server start --port 8300 --no-browser
