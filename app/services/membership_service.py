"""会员状态判断与权益门控。

支付开通逻辑在 payment_service；这里只做"当前会员是否有效/是否 PRO"的只读判定，
以及免费档月度配额计数，供 API 依赖层复用，避免在路由里散落过期判断。
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BodyAssessment, Membership, Plan, User

# 计入免费额度池的 PRO 功能 -> 成功记录所对应的模型。
# 口径（产品已确认）：体态评估与 AI 计划生成**共享**同一个月度额度池，
# 任一功能的一次成功调用都从同一池子扣减；这里保留 feature->model 映射仅用于
# breakdown 展示拆分，计数（quota_used）是跨所有模型求和。
QUOTA_FEATURE_MODELS = {
    "assess": BodyAssessment,
    "generate_plan": Plan,
}


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_membership_active(m: Membership | None, now: datetime | None = None) -> bool:
    """会员是否处于有效状态：已激活且未到期。"""
    if not m or not m.is_active:
        return False
    expire_at = _as_aware(m.expire_at)
    if expire_at is None:
        return False
    return expire_at > (now or datetime.now(timezone.utc))


def get_active_membership(db: Session, user_id: int) -> Membership | None:
    m = db.scalar(select(Membership).where(Membership.user_id == user_id))
    return m if is_membership_active(m) else None


def is_pro(db: Session, user_id: int) -> bool:
    m = get_active_membership(db, user_id)
    return bool(m and m.plan == "pro")


def get_or_create_membership(db: Session, user_id: int) -> Membership:
    """取当前用户会员记录；不存在则建一条 free 记录（与注册流程保持一致）。"""
    m = db.scalar(select(Membership).where(Membership.user_id == user_id))
    if not m:
        m = Membership(user_id=user_id, plan="free", is_active=False)
        db.add(m)
        db.commit()
        db.refresh(m)
    return m


def membership_view(m: Membership | None) -> dict:
    """序列化为 MembershipOut：统一“有效/是否 PRO/是否锁功能”的判定口径。"""
    active = is_membership_active(m)
    pro = bool(active and m and m.plan == "pro")
    return {
        "plan": (m.plan if m else "free"),
        "is_active": active,
        "is_pro": pro,
        "expire_at": m.expire_at if m else None,
        "payment_channel": m.payment_channel if m else None,
        # PRO 功能锁定：非有效 PRO 即锁定，前端据此弹付费墙
        "features_locked": not pro,
    }


# ---------- 免费档月度配额（共享池）----------
def month_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """返回当前自然月（UTC）的 [start, next_start) 边界，均为 aware UTC。"""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # 次月 1 日（12 月跨年由 replace 语义处理）
    next_month_year = start.year + (1 if start.month == 12 else 0)
    next_month_month = 1 if start.month == 12 else start.month + 1
    next_start = start.replace(year=next_month_year, month=next_month_month)
    return start, next_start


def _count_model(db: Session, model, user_id: int, start: datetime, end: datetime) -> int:
    stmt = (
        select(func.count())
        .select_from(model)
        .where(
            model.user_id == user_id,
            model.created_at >= start,
            model.created_at < end,
        )
    )
    return int(db.scalar(stmt) or 0)


def quota_breakdown(
    db: Session, user_id: int, now: datetime | None = None
) -> dict[str, int]:
    """返回本月各功能已用次数拆分，仅作展示用（不代表独立额度）。"""
    start, end = month_bounds(now)
    return {
        feature: _count_model(db, model, user_id, start, end)
        for feature, model in QUOTA_FEATURE_MODELS.items()
    }


def quota_used(db: Session, user_id: int, now: datetime | None = None) -> int:
    """免费用户本月（UTC 自然月）已用的共享额度次数。

    统计 body_assessments 与 plans 两张表本月成功记录数之和——
    assess 和 generate_plan 任一次调用都从同一池子扣减。
    门控在处理前查询，因此本次调用尚未产生记录，used 即此前已成功完成的次数。
    """
    return sum(quota_breakdown(db, user_id, now).values())


def quota_status(db: Session, user_id: int, now: datetime | None = None) -> dict:
    """返回共享额度池视图：scope/limit/used/remaining/reset_at/breakdown。

    PRO 用户语义上不限（remaining=None），但仍返回已用次数与拆分供展示。
    """
    limit = settings.free_quota_per_month
    used = quota_used(db, user_id, now)
    _, next_start = month_bounds(now)
    pro = is_pro(db, user_id)
    return {
        "scope": "shared",
        "limit": limit,
        "used": used,
        "remaining": None if pro else max(0, limit - used),
        "reset_at": next_start,
        "breakdown": quota_breakdown(db, user_id, now),
    }


def check_quota(
    db: Session, user_id: int, feature: str, now: datetime | None = None
) -> dict:
    """门控前置检查：返回 free 用户的共享额度池状态。

    `feature` 仅用于响应标识/日志，不影响计数（两个功能共享同一池子）。
    调用方在确认用户非 PRO 后调用本函数；若 used >= limit 应拒绝（402），
    否则放行（本次调用成功后会新增一条记录，自然计入当月额度）。
    """
    st = quota_status(db, user_id, now)
    st["feature"] = feature
    st["exhausted"] = st["used"] >= st["limit"]
    return st
