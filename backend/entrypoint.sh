#!/bin/sh
set -e

echo "[entrypoint] 等待 PostgreSQL 就绪并初始化种子数据…"
python -m app.seed

echo "[entrypoint] 启动溯源方后端，监听 7101…"
exec uvicorn app.main:app --host 0.0.0.0 --port 7101 --workers 2
