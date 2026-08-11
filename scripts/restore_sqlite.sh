#!/usr/bin/env bash
# SQLite 快照恢复（手动运维，危险操作）。
#
# 用法：
#   scripts/restore_sqlite.sh <容器内快照路径> <容器内目标路径> [--force]
#
# 默认拒绝覆盖已存在的目标；恢复演练请把目标指向 /data/backups/restore-test.db
# 之类的临时路径，严禁直接指向正在使用的 /data/formfit/formfit.db。
set -euo pipefail

CONTAINER="${CONTAINER:-formfit}"

if [[ $# -lt 2 ]]; then
  echo "用法: $0 <snapshot.db> <target.db> [--force]" >&2
  exit 64
fi

SNAPSHOT="$1"
TARGET="$2"
shift 2

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] 将在容器 ${CONTAINER} 内恢复 ${SNAPSHOT} -> ${TARGET}"
exec docker exec "${CONTAINER}" python -m app.ops.restore \
  --snapshot "${SNAPSHOT}" \
  --target "${TARGET}" \
  "$@"
