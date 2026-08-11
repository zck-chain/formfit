"""SQLite 一致性备份/恢复关键逻辑测试。"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.ops import backup as backup_mod
from app.ops import restore as restore_mod


def _build_source(db_path: Path) -> Path:
    """建一个带核心表与若干行的源库，返回路径。"""
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);
            CREATE TABLE memberships (id INTEGER PRIMARY KEY, user_id INTEGER);
            CREATE TABLE body_assessments (id INTEGER PRIMARY KEY, user_id INTEGER);
            CREATE TABLE plans (id INTEGER PRIMARY KEY, user_id INTEGER);
            CREATE TABLE workout_logs (id INTEGER PRIMARY KEY, user_id INTEGER);
            CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER);
            INSERT INTO users (email) VALUES ('a@t.com'), ('b@t.com'), ('c@t.com');
            INSERT INTO orders (user_id) VALUES (1), (2);
            """
        )
        con.commit()
    finally:
        con.close()
    return db_path


def test_backup_creates_consistent_snapshot_with_checksum(tmp_path):
    src = _build_source(tmp_path / "formfit.db")
    out = tmp_path / "backups"
    now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)

    result = backup_mod.create_backup(src, out, retain_days=14, now=now)

    assert result.snapshot.exists()
    assert result.snapshot.name == "formfit-20260811-120000.db"
    # 校验文件存在且摘要匹配
    cpath = result.snapshot.with_suffix(result.snapshot.suffix + ".sha256")
    assert cpath.exists()
    assert restore_mod.verify_checksum_file(result.snapshot) is True
    # 快照行数与源一致
    counts = restore_mod.table_counts(result.snapshot)
    assert counts["users"] == 3
    assert counts["orders"] == 2


def test_backup_uses_online_backup_not_raw_copy(tmp_path, monkeypatch):
    """确保走 sqlite3 .backup API（逐页一致性拷贝），而不是裸文件复制。"""
    src = _build_source(tmp_path / "formfit.db")
    calls = {"backup": 0}
    orig = backup_mod._online_copy

    def _spy(source, dest):
        calls["backup"] += 1
        return orig(source, dest)

    monkeypatch.setattr(backup_mod, "_online_copy", _spy)
    backup_mod.create_backup(src, tmp_path / "out", retain_days=14)
    assert calls["backup"] == 1


def test_restore_refuses_overwrite_without_force(tmp_path):
    src = _build_source(tmp_path / "formfit.db")
    out = tmp_path / "backups"
    result = backup_mod.create_backup(src, out)
    target = tmp_path / "restored.db"
    target.write_text("existing")

    with pytest.raises(FileExistsError):
        restore_mod.restore_backup(result.snapshot, target, force=False)
    # 原文件未被动过
    assert target.read_text() == "existing"


def test_restore_roundtrip_preserves_row_counts(tmp_path):
    src = _build_source(tmp_path / "formfit.db")
    result = backup_mod.create_backup(src, tmp_path / "backups")
    target = tmp_path / "restored.db"

    restored = restore_mod.restore_backup(result.snapshot, target)

    assert restored.target.exists()
    assert restored.table_counts["users"] == 3
    assert restored.table_counts["orders"] == 2
    # 恢复后的库能独立打开且 integrity_check=ok
    con = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()


def test_restore_detects_checksum_tampering(tmp_path):
    src = _build_source(tmp_path / "formfit.db")
    result = backup_mod.create_backup(src, tmp_path / "backups")
    # 篡改快照一个字节
    data = bytearray(result.snapshot.read_bytes())
    data[100] ^= 0xFF
    result.snapshot.write_bytes(bytes(data))

    with pytest.raises(Exception, match="SHA-256|integrity|缺少"):
        restore_mod.restore_backup(result.snapshot, tmp_path / "restored.db")


def test_prune_removes_snapshots_older_than_retention(tmp_path):
    out = tmp_path / "backups"
    out.mkdir()
    # 造三个带时间戳的快照文件
    for name in ("formfit-20260801-000000.db", "formfit-20260805-000000.db"):
        (out / name).write_bytes(b"x")
        (out / (name + ".sha256")).write_text("abc  x\n")
    keep = out / "formfit-20260811-000000.db"
    keep.write_bytes(b"y")
    (keep.with_suffix(keep.suffix + ".sha256")).write_text("abc  y\n")

    now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
    # 把旧文件的 mtime 也调到过去
    for name in ("formfit-20260801-000000.db", "formfit-20260805-000000.db"):
        old = (now - timedelta(days=20)).timestamp()
        import os
        os.utime(out / name, (old, old))

    removed = backup_mod.prune_old_backups(out, retain_days=14, now=now)
    assert len(removed) == 2
    assert keep.exists()
    # 校验文件随快照一起删除
    assert not (out / "formfit-20260801-000000.db.sha256").exists()


def test_backup_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_mod.create_backup(tmp_path / "nope.db", tmp_path / "out")
