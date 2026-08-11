"""鉴权依赖：从 Bearer token 解析当前用户。"""
from fastapi import Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db
from app.models import User
from app.services import membership_service

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已停用")
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def get_optional_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """可选登录：用于公开接口，未登录返回 None。"""
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    return db.get(User, int(payload["sub"]))


# ---------- PRO 会员门控 ----------
# PRO 用户不限；free 用户每个 PRO 功能每月各 FREE_QUOTA_PER_MONTH 次（按自然月 UTC），
# 超额返回 402 quota_exhausted，未登录/非 PRO 且无可用额度返回 402 pro_required。

# 需要 PRO 权益的功能标识，响应体回传给客户端用于引导付费墙
PRO_FEATURES = {
    "assess": "体态评估",
    "generate_plan": "AI 训练计划生成",
}


def require_pro_membership(feature: str):
    """生成一个依赖：放行有效 PRO 会员；free 用户在月度配额内放行，超额返回 402。

    用法（路由参数）：
        @router.post("/assess", dependencies=[Depends(require_pro_membership("assess"))])

    计数口径（自然月 UTC）：
        - assess      → 本月 body_assessments 成功记录数
        - generate_plan → 本月 plans 记录数
    门控在业务处理前查询，因此 used 为此前已成功完成的次数；本次成功后由路由新增记录，
    自然计入当月额度。PRO 用户不受额度限制。
    """

    label = PRO_FEATURES.get(feature, feature)

    def _dependency(
        response: Response,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        if membership_service.is_pro(db, user.id):
            return user

        quota = membership_service.check_quota(db, user.id, feature)
        # 响应头告知本次门控评估时（业务处理前）的额度快照；调用成功后本次记录才入账，
        # 客户端如需调用后的剩余次数，再拉一次 GET /api/membership。
        response.headers["X-Quota-Feature"] = feature
        response.headers["X-Quota-Limit"] = str(quota["limit"])
        response.headers["X-Quota-Used"] = str(quota["used"])
        response.headers["X-Quota-Remaining"] = str(quota["remaining"])
        response.headers["X-Quota-Reset"] = quota["reset_at"].isoformat()

        if quota["exhausted"]:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "quota_exhausted",
                    "feature": feature,
                    "message": f"本月{label}免费额度已用完，升级 PRO 不限次",
                    "limit": quota["limit"],
                    "used": quota["used"],
                    "reset_at": quota["reset_at"].isoformat(),
                    # 客户端据此跳转付费墙：拉取 /api/payment/plans
                    "upgrade_hint": "/api/payment/plans",
                },
            )
        return user

    return _dependency
