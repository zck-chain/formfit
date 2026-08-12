"""管理员写操作审计服务。

把后台管理员对用户/会员的写操作记录到 `admin_audit_events`，与支付对账表
`payment_audit_events` 分离。所有快照均为白名单小 JSON，严禁写入密码哈希、
密钥、Cookie/Authorization 等敏感数据。

调用方负责在同一事务内：先读 before、再改动实体、最后调用 record_event，
由路由层统一 commit，确保业务变更与审计行原子落库。
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging_config import request_id_ctx
from app.models import Membership, User
from app.models.admin_audit import AdminAuditEvent, ADMIN_ACTIONS

# 动作 -> 中文展示名（后台审计页用）
ACTION_ZH = {
    "grant_membership": "发放会员",
    "revoke_membership": "收回会员",
    "toggle_user": "启用/停用用户",
}

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


# ---------- 查询 / 序列化 ----------
# 序列化白名单：只输出这些字段，绝不含密码哈希/密钥/Cookie/Authorization。
# before/after 本身即写入时的白名单小快照（snapshot_*），此处原样透传。
def serialize_event(
    event: AdminAuditEvent,
    admin: User | None = None,
    target: User | None = None,
) -> dict[str, Any]:
    """把审计事件序列化为 UI/API 友好的 dict。admin/target 用于补全邮箱展示。"""
    return {
        "id": event.id,
        "created_at": _iso(event.created_at),
        "admin_id": event.admin_id,
        "admin_email": getattr(admin, "email", None),
        "action": event.action,
        "action_label": ACTION_ZH.get(event.action, event.action),
        "target_user_id": event.target_user_id,
        "target_email": getattr(target, "email", None),
        "reason": event.reason,
        "before": event.before_json or {},
        "after": event.after_json or {},
        "request_id": event.request_id,
        "idempotency_key": event.idempotency_key,
    }


def list_events(
    db: Session,
    *,
    action: str | None = None,
    admin_id: int | None = None,
    target_user_id: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """分页查询审计事件，按 id 倒序（最新在前）。

    返回 (items, total)；items 为已序列化 dict 列表，附带操作者/目标邮箱。
    用两条 in_ 查询批量补全用户信息，避免 N+1。
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    stmt = select(AdminAuditEvent)
    if action:
        stmt = stmt.where(AdminAuditEvent.action == action)
    if admin_id:
        stmt = stmt.where(AdminAuditEvent.admin_id == admin_id)
    if target_user_id:
        stmt = stmt.where(AdminAuditEvent.target_user_id == target_user_id)
    if start is not None:
        stmt = stmt.where(AdminAuditEvent.created_at >= start)
    if end is not None:
        stmt = stmt.where(AdminAuditEvent.created_at <= end)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    events = db.scalars(
        stmt.order_by(AdminAuditEvent.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()

    # 批量解析操作者/目标用户邮箱（单次 in_ 查询）
    user_ids: set[int] = set()
    for e in events:
        user_ids.add(e.admin_id)
        user_ids.add(e.target_user_id)
    users: dict[int, User] = {}
    if user_ids:
        users = {
            u.id: u
            for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()
        }

    items = [
        serialize_event(e, users.get(e.admin_id), users.get(e.target_user_id))
        for e in events
    ]
    return items, total
