"""会员态查询接口：供 App 在启动/支付完成后刷新当前权益与付费墙状态。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.payment import MembershipOut
from app.services import membership_service

router = APIRouter(prefix="/api/membership", tags=["membership"])


@router.get("", response_model=MembershipOut)
def get_membership(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回当前登录用户的会员状态与免费额度。

    免费用户返回 plan=free/is_active=false/is_pro=false/features_locked=true，
    并在 quota 中给出每个 PRO 功能本月剩余次数，App 据此展示"本月剩余 X 次"与付费墙；
    支付成功后重新拉取本接口即可刷新权益，无需重新登录。
    """
    m = membership_service.get_or_create_membership(db, user.id)
    view = membership_service.membership_view(m)
    view["quota"] = membership_service.all_quota_status(db, user.id)
    return MembershipOut(**view)
