#!/usr/bin/env bash
# 容器入口：建表/迁移 -> 首次种子 -> 启动 uvicorn。
#
# 任何一步失败立即退出（fail-fast），让容器编排能观测到启动失败并重启。
set -euo pipefail

cd /app

echo "[entrypoint] APP_ENV=${APP_ENV:-development}"

# 1) 数据库迁移（Alembic）。SQLite 文件位于持久卷，首次启动自动建表。
#    迁移失败直接中止启动，避免带着错误 schema 对外服务。
if [[ "${RUN_MIGRATIONS:-1}" == "1" ]]; then
  echo "[entrypoint] 执行数据库迁移..."
  alembic upgrade head
fi

# 2) 动作数据：仅在 exercises 表为空时导入，避免每次启动重复写入。
if [[ "${RUN_SEED:-1}" == "1" ]]; then
  EXERCISE_COUNT=$(python -c "
import sqlite3, os
url = os.environ.get('DATABASE_URL','')
# 仅处理 sqlite 文件库
path = url.replace('sqlite:///','') if url.startswith('sqlite:///') else ''
if path and path != ':memory:':
    con = sqlite3.connect(path)
    try:
        print(con.execute('SELECT COUNT(*) FROM exercises').fetchone()[0])
    except sqlite3.OperationalError:
        print(0)
    finally:
        con.close()
else:
    print(0)
" 2>/dev/null || echo 0)

  if [[ "${EXERCISE_COUNT}" == "0" ]]; then
    echo "[entrypoint] 动作表为空，开始导入 1324 个动作..."
    python -m scripts.seed_exercises
  else
    echo "[entrypoint] 已有 ${EXERCISE_COUNT} 个动作，跳过导入"
  fi
fi

echo "[entrypoint] 启动: $*"
exec "$@"
