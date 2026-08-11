"""鉴权依赖：从 Bearer token 解析当前用户。"""
from fastapi import Depends, HTTPException, status
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
# 当前为"硬门控"：仅有效且未过期的 PRO 会员可用。
# 免费额度策略待产品最终确认；扩展点见 require_pro_membership 内的 FREE_QUOTA 注释。

# 需要 PRO 权益的功能标识，响应体回传给客户端用于引导付费墙
PRO_FEATURES = {
    "assess": "体态评估",
    "generate_plan": "AI 训练计划生成",
}


def require_pro_membership(feature: str):
    """生成一个依赖：放行有效 PRO 会员，free 用户返回 402 并携带付费墙引导信息。

    用法（路由参数）：
        @router.post("/assess", dependencies=[Depends(require_pro_membership("assess"))])

    配额扩展点（产品确认免费额度后实现）：
        在 402 之前查询 free 用户已用额度（如 body_assessments / plans 计数），
        未超额则放行，超额再 402。门控签名保持不变，路由无需改动。
    """

    label = PRO_FEATURES.get(feature, feature)

    def _dependency(
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        # TODO(quota): 免费额度策略——free 用户在配额内放行，超额后再进入 PRO 校验。
        if membership_service.is_pro(db, user.id):
            return user
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "pro_required",
                "feature": feature,
                "message": f"{label}为 PRO 会员功能",
                # 客户端据此跳转付费墙：拉取 /api/payment/plans
                "upgrade_hint": "/api/payment/plans",
            },
        )

    return _dependency
