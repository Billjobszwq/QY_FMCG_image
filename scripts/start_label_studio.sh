#!/usr/bin/env bash
# Label Studio 启动脚本（本地原生，端口 8300）
# 启用旧版 token 认证以支持 API / ML 后端 token 访问。
set -e
# 修正：仅上跳一级到项目根（旧版 ../.. 会把数据目录落到项目父目录）
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

export LABEL_STUDIO_BASE_DATA_DIR="$ROOT/.label-studio"
export LABEL_STUDIO_PORT=8300
export LABEL_STUDIO_ENABLE_LEGACY_TOKEN_AUTH=true
export LABEL_STUDIO_DISABLE_SIGNUP_WITHOUT_LINK=false
# 1.23 起 default=PostgreSQL；本机原生开发固定 SQLite（M6 再迁 PG），
# 数据库文件落在项目内 .label-studio/label_studio.sqlite3
export DJANGO_DB=sqlite

echo "启动 Label Studio: http://127.0.0.1:8300  (数据目录: $LABEL_STUDIO_BASE_DATA_DIR)"
exec python -m label_studio.server start --port 8300 --no-browser
