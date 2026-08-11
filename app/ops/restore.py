"""SQLite 快照恢复。

安全原则：
- **默认拒绝覆盖**已存在的目标文件，必须显式 `--force` 才会覆盖；
  恢复演练请把 `--target` 指向临时目录。
- 恢复前校验快照的 SHA-256（若存在 `.sha256`）与 `PRAGMA integrity_check`。
- 使用 SQLite 在线备份 API 把快照页拷贝到全新目标文件，得到干净一致的库，
  而不是直接移动/改名快照文件。
- 恢复后再次校验目标库可打开、核心表存在，并打印关键表行数供人工核对。

严禁用本脚本直接覆盖真实开发库或生产库。
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from app.ops.backup import REQUIRED_TABLES, _online_copy, verify_snapshot

logger = logging.getLogger("formfit.restore")


@dataclass(frozen=True)
class RestoreResult:
    target: Path
    table_counts: dict[str, int]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_checksum_file(snapshot: Path) -> bool:
    """若存在 `<snapshot>.sha256`，校验其摘要与文件一致。无校验文件时返回 None 语义。

    返回 True 表示通过；返回 False 表示校验文件存在但不匹配。
    无校验文件抛 FileNotFoundError 让调用方决定是否放行。
    """
    cpath = snapshot.with_suffix(snapshot.suffix + ".sha256")
    if not cpath.exists():
        raise FileNotFoundError(cpath)
    expected = cpath.read_text(encoding="utf-8").split()[0].strip().lower()
    return _sha256(snapshot) == expected


def table_counts(path: Path, tables: tuple[str, ...] = REQUIRED_TABLES) -> dict[str, int]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        present = {
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        result: dict[str, int] = {}
        for t in tables:
            if t in present:
                result[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return result
    finally:
        con.close()


def restore_backup(snapshot: Path, target: Path, *, force: bool = False) -> RestoreResult:
    """把快照恢复到全新目标文件。target 已存在时默认拒绝。"""
    snapshot = Path(snapshot)
    target = Path(target)

    if not snapshot.exists():
        raise FileNotFoundError(f"快照不存在：{snapshot}")
    if target.exists():
        if not force:
            raise FileExistsError(
                f"目标已存在，拒绝覆盖：{target}（如确认无误请加 --force）"
            )
        target.unlink()

    # 校验摘要（若提供）
    try:
        if not verify_checksum_file(snapshot):
            raise RuntimeError("快照 SHA-256 校验失败，文件可能已损坏或被篡改")
    except FileNotFoundError:
        logger.warning("未找到 .sha256 校验文件，跳过摘要校验")

    # 校验快照完整性与核心表
    verify_snapshot(snapshot)

    target.parent.mkdir(parents=True, exist_ok=True)

    # 用在线备份 API 把快照拷到新文件（得到干净一致的库）
    source = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    dest = sqlite3.connect(target)
    try:
        _online_copy(source, dest)
    finally:
        dest.close()
        source.close()

    # 校验恢复结果
    verify_snapshot(target)
    counts = table_counts(target)

    logger.info(
        "恢复完成",
        extra={
            "event": "restore_completed",
            "target": str(target),
            "tables": list(counts.keys()),
        },
    )
    return RestoreResult(target=target, table_counts=counts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SQLite 快照恢复")
    parser.add_argument("--snapshot", required=True, help="备份快照 .db 路径")
    parser.add_argument("--target", required=True, help="恢复目标 .db 路径")
    parser.add_argument(
        "--force",
        action="store_true",
        help="允许覆盖已存在的目标文件（危险，演练时不要指向真实库）",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        result = restore_backup(
            Path(args.snapshot), Path(args.target), force=args.force
        )
    except FileExistsError as exc:
        logger.error("%s", exc)
        return 2
    except Exception as exc:
        logger.error("恢复失败：%s", exc)
        return 1

    print(f"restored={result.target}")
    for table, n in result.table_counts.items():
        print(f"count {table}={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
