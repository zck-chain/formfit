"""/healthz 健康检查。

- 存活：进程能响应即视为存活。
- 就绪：执行一条最轻量的数据库查询（SELECT 1），失败返回 503。
- 响应体刻意保持极简，不泄露路径、密钥、连接串或任何内部细节。
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import engine

logger = logging.getLogger(__name__)
router = APIRouter()


def check_database() -> tuple[bool, str | None]:
    """对数据库执行轻量探活查询。

    返回 (ok, error_reason)。error_reason 只给笼统类别，不含底层连接信息。
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, None
    except SQLAlchemyError:
        # 只记录到日志，不把引擎/连接串细节带回响应体
        logger.exception("healthz: database ping failed")
        return False, "database unavailable"
    except Exception:  # pragma: no cover - 防御性
        logger.exception("healthz: unexpected error during database ping")
        return False, "database unavailable"


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """容器/编排层探针：进程存活 + 数据库可查询。

    数据库异常返回 503，便于编排重启或摘流；响应体不含敏感信息。
    """
    ok, reason = check_database()
    status: Literal["ok", "error"] = "ok" if ok else "error"
    from fastapi.responses import JSONResponse

    body = {"status": status}
    if not ok:
        body["reason"] = reason or "error"  # type: ignore[assignment]
        return JSONResponse(status_code=503, content=body)
    return body
