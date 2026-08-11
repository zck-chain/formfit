#!/usr/bin/env bash
# SQLite 每日一致性备份 —— 供 1Panel「计划任务」调用。
#
# 默认通过 `docker exec` 在运行中的后端容器内执行（容器内有 Python + sqlite3，
# 且数据库/备份目录都是已挂载的持久卷），保证用的是在线备份 API 而不是裸 cp。
#
# 环境变量：
#   CONTAINER    后端容器名，默认 formfit
#   DB_PATH      容器内源数据库，默认 /data/formfit/formfit.db
#   BACKUP_DIR   容器内快照目录，默认 /data/backups
#   RETAIN_DAYS  保留天数，默认 14
#
# 退出码：0 成功；非 0 失败（1Panel 会据此告警）。
# 腾讯云 COS 上传由 1Panel 的对象存储同步任务负责，本脚本不接触任何 COS 密钥。
set -euo pipefail

CONTAINER="${CONTAINER:-formfit}"
DB_PATH="${DB_PATH:-/data/formfit/formfit.db}"
BACKUP_DIR="${BACKUP_DIR:-/data/backups}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] 备份 ${CONTAINER}:${DB_PATH} -> ${BACKUP_DIR}（保留 ${RETAIN_DAYS} 天）"
exec docker exec "${CONTAINER}" python -m app.ops.backup \
  --db "${DB_PATH}" \
  --out "${BACKUP_DIR}" \
  --retain-days "${RETAIN_DAYS}"
