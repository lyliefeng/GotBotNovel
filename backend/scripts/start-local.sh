#!/bin/bash
# 本地 SQLite 启动脚本：执行迁移后启动 FastAPI 服务。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${BACKEND_ROOT}"
mkdir -p data logs storage/generated_covers

echo "🔄 使用 SQLite 执行数据库迁移..."
alembic -c alembic-sqlite.ini upgrade head

echo "🚀 启动 GotBotNovel..."
exec uvicorn app.main:app \
    --host "${APP_HOST:-127.0.0.1}" \
    --port "${APP_PORT:-8000}" \
    --log-level "${LOG_LEVEL:-info}" \
    --access-log
