"""鉴权依赖：Bearer 优先、Cookie 兜底，并对 Cookie 写操作做 CSRF 校验。"""
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.core.web_auth import (
    csrf_required,
    read_session_token,
    validate_csrf,
)
from app.db.session import get_db
from app.models import User
from app.services import membership_service

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def csrf_protect(request: Request) -> None:
    """Cookie 认证下的写操作必须通过双提交 CSRF 校验。

    - Bearer 认证（native）不依赖 cookie，浏览器不会自动附带，免校验；
    - 安全方法（GET/HEAD/OPTIONS）不改变状态，免校验；
    - 仅当请求靠会话 cookie 认证且为写方法时，比对 X-CSRF-Token 头与 csrftoken cookie，
      缺失/不匹配一律 403 csrf_failed（常量时间比较在 web_auth.validate_csrf 内）。
    """
    if not csrf_required(request):
        return
    if not validate_csrf(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "csrf_failed"},
        )


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    # CSRF 在认证之前校验：cookie 写操作缺/错 CSRF 应直接 403，
    # 而不是走到 401 暴露「该 cookie 是否对应有效用户」。
    csrf_protect(request)

    # oauth2_scheme 已解析 Bearer；若它没拿到（cookie 链路），再从 cookie 兜底。
    resolved = token if token else read_session_token(request)
    if not resolved:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(resolved)
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
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """可选登录：用于公开接口，未登录返回 None。

    Cookie 链路的写操作同样要过 CSRF（虽然当前没有写接口用本依赖，
    保留一致性以防未来误用导致越权伪造）。
    """
    csrf_protect(request)
    resolved = token if token else read_session_token(request)
    if not resolved:
        return None
    payload = decode_token(resolved)
    if not payload:
        return None
    return db.get(User, int(payload["sub"]))


# ---------- PRO 会员门控 ----------
# PRO 用户不限；free 用户体态评估与 AI 计划生成**共享**每月 FREE_QUOTA_PER_MONTH 次
# （按自然月 UTC，两功能合计），超额返回 402 quota_exhausted。

# 需要 PRO 权益的功能标识，响应体回传给客户端用于引导付费墙
PRO_FEATURES = {
    "assess": "体态评估",
    "generate_plan": "AI 训练计划生成",
}


def require_pro_membership(feature: str):
    """生成一个依赖：放行有效 PRO 会员；free 用户在共享月度配额内放行，超额返回 402。

    用法（路由参数）：
        @router.post("/assess", dependencies=[Depends(require_pro_membership("assess"))])

    计数口径（自然月 UTC，共享池）：本月 body_assessments 与 plans 成功记录数**之和**；
    assess 和 generate_plan 任一次调用都从同一池子扣减。
    门控在业务处理前查询，因此 used 为此前已成功完成的次数；本次成功后由路由新增记录，
    自然计入当月额度。PRO 用户不受额度限制。`feature` 仅用于响应标识，不影响计数。
    """

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
                    "message": "本月免费额度已用完，升级 PRO 不限次",
                    "limit": quota["limit"],
                    "used": quota["used"],
                    "reset_at": quota["reset_at"].isoformat(),
                    # 客户端据此跳转付费墙：拉取 /api/payment/plans
                    "upgrade_hint": "/api/payment/plans",
                },
            )
        return user

    return _dependency
