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
