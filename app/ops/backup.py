"""SQLite 一致性备份。

使用 SQLite 的在线备份 API（Python `connection.backup()`，等价于 sqlite3 CLI 的
`.backup` 命令）生成快照：它会逐页拷贝并正确处理并发写入，**不要**直接复制正在写入的
数据库文件——直接 cp 可能得到一个不一致、甚至损坏的副本。

产物：
- `<db_stem>-<UTC时间戳>.db`        一致性快照
- `<db_stem>-<UTC时间戳>.db.sha256` 该快照的 SHA-256（十六进制摘要）

快照生成后立即执行 `PRAGMA integrity_check`，失败则删除快照并返回非零退出码。
旧快照按保留天数清理（默认 14 天），腾讯云 COS 上传由 1Panel/安全配置负责，
本脚本**绝不**硬编码任何 COS 密钥。
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("formfit.backup")

# 备份完整性校验要求存在的核心业务表（缺表说明快照异常或库不对）。
REQUIRED_TABLES = (
    "users",
    "memberships",
    "body_assessments",
    "plans",
    "workout_logs",
    "orders",
)


@dataclass(frozen=True)
class BackupResult:
    snapshot: Path
    checksum: str
    size_bytes: int
    pruned: list[Path]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _online_copy(source: sqlite3.Connection, dest: sqlite3.Connection) -> None:
    """SQLite 在线备份 API 的薄封装（等价 sqlite3 CLI `.backup`）。

    独立成函数便于测试确认走的是逐页一致性拷贝，而不是裸文件复制。
    """
    source.backup(dest)


def _write_checksum_file(snapshot: Path, digest: str) -> Path:
    cpath = snapshot.with_suffix(snapshot.suffix + ".sha256")
    # 格式与 `sha256sum` 一致："<digest>  <filename>\n"
    cpath.write_text(f"{digest}  {snapshot.name}\n", encoding="utf-8")
    return cpath


def verify_snapshot(snapshot: Path) -> str:
    """打开快照并跑 integrity_check + 核心表存在性校验。

    通过返回 "ok"；失败抛 RuntimeError（调用方负责清理）。
    """
    if not snapshot.exists():
        raise RuntimeError(f"快照不存在：{snapshot}")
    uri = f"file:{snapshot}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        row = con.execute("PRAGMA integrity_check").fetchone()
        if not row or row[0] != "ok":
            raise RuntimeError(f"integrity_check 失败：{row[0] if row else 'empty'}")
        tables = {
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = [t for t in REQUIRED_TABLES if t not in tables]
        if missing:
            raise RuntimeError(f"快照缺少核心表：{', '.join(missing)}")
    finally:
        con.close()
    return "ok"


def create_backup(
    db_path: Path,
    out_dir: Path,
    retain_days: int = 14,
    *,
    now: datetime | None = None,
) -> BackupResult:
    """创建一份一致性快照并按保留天数清理旧快照。

    `now` 仅用于测试注入可预测的时间戳。
    """
    db_path = Path(db_path)
    out_dir = Path(out_dir)
    if not db_path.exists():
        raise FileNotFoundError(f"数据库文件不存在：{db_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    ts = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    snapshot = out_dir / f"{db_path.stem}-{ts}.db"

    # 在线备份 API：源以只读方式打开，目标为新文件，逐页拷贝保证一致性。
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dest = sqlite3.connect(snapshot)
    try:
        _online_copy(source, dest)
    except Exception:
        dest.close()
        source.close()
        if snapshot.exists():
            snapshot.unlink()
        raise
    finally:
        dest.close()
        source.close()

    # 校验新快照；损坏立即删除，避免把坏快照留给恢复流程。
    try:
        verify_snapshot(snapshot)
    except Exception:
        if snapshot.exists():
            snapshot.unlink(missing_ok=True)
        raise

    digest = _sha256(snapshot)
    _write_checksum_file(snapshot, digest)
    pruned = prune_old_backups(out_dir, retain_days, now=now)

    result = BackupResult(
        snapshot=snapshot,
        checksum=digest,
        size_bytes=snapshot.stat().st_size,
        pruned=pruned,
    )
    logger.info(
        "备份完成",
        extra={
            "event": "backup_created",
            "snapshot": snapshot.name,
            "size_bytes": result.size_bytes,
            "sha256": digest[:16],
            "pruned": len(pruned),
        },
    )
    return result


def prune_old_backups(
    out_dir: Path,
    retain_days: int,
    *,
    now: datetime | None = None,
) -> list[Path]:
    """删除修改时间早于保留窗口的 .db 快照及其 .sha256。"""
    if retain_days < 0:
        return []
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retain_days)
    removed: list[Path] = []
    for snapshot in sorted(Path(out_dir).glob("*.db")):
        mtime = datetime.fromtimestamp(snapshot.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            checksum = snapshot.with_suffix(snapshot.suffix + ".sha256")
            snapshot.unlink(missing_ok=True)
            checksum.unlink(missing_ok=True)
            removed.append(snapshot)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SQLite 一致性备份")
    parser.add_argument("--db", required=True, help="源数据库路径，如 /data/formfit.db")
    parser.add_argument("--out", required=True, help="快照输出目录，如 /data/backups")
    parser.add_argument(
        "--retain-days", type=int, default=14, help="保留天数，默认 14"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        result = create_backup(
            Path(args.db), Path(args.out), retain_days=args.retain_days
        )
    except Exception as exc:
        logger.error("备份失败：%s", exc)
        return 1

    print(f"snapshot={result.snapshot}")
    print(f"sha256={result.checksum}")
    print(f"size_bytes={result.size_bytes}")
    print(f"pruned={len(result.pruned)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
