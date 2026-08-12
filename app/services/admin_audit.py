"""管理员写操作审计服务。

把后台管理员对用户/会员的写操作记录到 `admin_audit_events`，与支付对账表
`payment_audit_events` 分离。所有快照均为白名单小 JSON，严禁写入密码哈希、
密钥、Cookie/Authorization 等敏感数据。

调用方负责在同一事务内：先读 before、再改动实体、最后调用 record_event，
由路由层统一 commit，确保业务变更与审计行原子落库。
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging_config import request_id_ctx
from app.models import Membership, User
from app.models.admin_audit import AdminAuditEvent

# 幂等去重窗口：同一 admin 对同一 target 的同一动作、携带相同 Idempotency-Key，
# 在该窗口内视为重复提交，不再重复执行（v1 单管理员自用，窗口取 5 分钟足够覆盖表单双击）。
IDEMPOTENCY_WINDOW = timedelta(minutes=5)


def _iso(dt: datetime | None) -> str | None:
    """把 datetime 序列化为 ISO 字符串；naive 视为 UTC。None 透传。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def snapshot_membership(m: Membership | None) -> dict[str, Any]:
    """会员关键字段快照，用于 before/after。只记状态字段，不记支付凭证/订阅 id。"""
    if m is None:
        return {
            "exists": False,
            "plan": None,
            "is_active": None,
            "start_at": None,
            "expire_at": None,
        }
    return {
        "exists": True,
        "plan": m.plan,
        "is_active": bool(m.is_active),
        "start_at": _iso(m.start_at),
        "expire_at": _iso(m.expire_at),
    }


def snapshot_user(u: User | None) -> dict[str, Any]:
    """用户启停状态快照。只记 is_active/role，不记邮箱/密码等。"""
    if u is None:
        return {"exists": False, "is_active": None}
    return {"exists": True, "is_active": bool(u.is_active), "role": u.role}


def is_replay(
    db: Session,
    *,
    admin_id: int,
    action: str,
    target_user_id: int,
    idempotency_key: str | None,
    now: datetime | None = None,
) -> AdminAuditEvent | None:
    """若在窗口内存在相同 (admin, action, target, idempotency_key) 的审计记录，
    视为重复提交，返回那条记录；否则返回 None。未携带幂等键时不去重。"""
    if not idempotency_key:
        return None
    now = now or datetime.now(timezone.utc)
    window_start = now - IDEMPOTENCY_WINDOW
    return db.scalar(
        select(AdminAuditEvent)
        .where(
            AdminAuditEvent.admin_id == admin_id,
            AdminAuditEvent.action == action,
            AdminAuditEvent.target_user_id == target_user_id,
            AdminAuditEvent.idempotency_key == idempotency_key,
            AdminAuditEvent.created_at >= window_start,
        )
        .order_by(AdminAuditEvent.id.desc())
        .limit(1)
    )


def record_event(
    db: Session,
    *,
    admin_id: int,
    action: str,
    target_user_id: int,
    before: dict[str, Any],
    after: dict[str, Any],
    reason: str | None = None,
    request_id: str | None = None,
    idempotency_key: str | None = None,
) -> AdminAuditEvent:
    """写一条管理员审计记录。request_id 缺省时从上下文变量取（访问日志中间件已设置）。"""
    event = AdminAuditEvent(
        admin_id=admin_id,
        action=action,
        target_user_id=target_user_id,
        before_json=before or {},
        after_json=after or {},
        reason=(reason.strip() if reason and reason.strip() else None),
        request_id=request_id or request_id_ctx.get(),
        idempotency_key=idempotency_key or None,
    )
    db.add(event)
    return event
