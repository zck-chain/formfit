"""会员状态判断与权益门控。

支付开通逻辑在 payment_service；这里只做"当前会员是否有效/是否 PRO"的只读判定，
供 API 依赖层复用，避免在路由里散落过期判断。
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Membership, User


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
