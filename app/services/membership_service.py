"""会员状态判断与权益门控。

支付开通逻辑在 payment_service；这里只做"当前会员是否有效/是否 PRO"的只读判定，
以及免费档月度配额计数，供 API 依赖层复用，避免在路由里散落过期判断。
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BodyAssessment, Membership, Plan, User

# 受 PRO 门控、同时计入免费额度的功能 -> 计数所依据的模型（成功记录数）。
# 口径：每个功能每月各 FREE_QUOTA_PER_MONTH 次（非共享池）。
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


# ---------- 免费档月度配额 ----------
def month_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """返回当前自然月（UTC）的 [start, next_start) 边界，均为 aware UTC。"""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # 次月 1 日（12 月跨年由 monthrange/date 语义处理）
    next_month_year = start.year + (1 if start.month == 12 else 0)
    next_month_month = 1 if start.month == 12 else start.month + 1
    next_start = start.replace(year=next_month_year, month=next_month_month)
    return start, next_start


def quota_used(db: Session, user_id: int, feature: str, now: datetime | None = None) -> int:
    """免费用户某功能本月（UTC 自然月）已成功使用次数。

    `assess` 计 body_assessments 成功记录；`generate_plan` 计 plans 记录。
    仅统计本月创建的记录——门控在处理前查询，因此本次调用尚未产生记录，
    used 即此前已成功完成的次数。
    """
    model = QUOTA_FEATURE_MODELS.get(feature)
    if model is None:
        # 未纳入配额的功能不计数（交由上层 PRO 硬门控）
        return 0
    start, end = month_bounds(now)
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


def quota_status(
    db: Session, user_id: int, feature: str, now: datetime | None = None
) -> dict:
    """返回单个功能的配额视图：limit/used/remaining/reset_at。

    PRO 用户语义上不限（remaining 以 None 表示无上限），但仍返回已用次数供展示。
    """
    limit = settings.free_quota_per_month
    used = quota_used(db, user_id, feature, now)
    _, next_start = month_bounds(now)
    return {
        "feature": feature,
        "limit": limit,
        "used": used,
        # PRO 用户不限；free 用户剩余 = max(0, limit-used)
        "remaining": None,
        "reset_at": next_start,
    }


def all_quota_status(db: Session, user_id: int, now: datetime | None = None) -> dict[str, dict]:
    """返回所有受门控功能的配额状态，供 /api/membership 一次性展示。"""
    pro = is_pro(db, user_id)
    out: dict[str, dict] = {}
    for feature in QUOTA_FEATURE_MODELS:
        st = quota_status(db, user_id, feature, now)
        if pro:
            st["remaining"] = None
        else:
            st["remaining"] = max(0, st["limit"] - st["used"])
        out[feature] = st
    return out


def check_quota(
    db: Session, user_id: int, feature: str, now: datetime | None = None
) -> dict:
    """门控前置检查：返回 free 用户在该功能上的配额状态。

    调用方在确认用户非 PRO 后调用本函数；若 used >= limit 应拒绝（402），
    否则放行（本次调用成功后会新增一条记录，自然计入下月之前的额度）。
    """
    st = quota_status(db, user_id, feature, now)
    st["remaining"] = max(0, st["limit"] - st["used"])
    st["exhausted"] = st["used"] >= st["limit"]
    return st
