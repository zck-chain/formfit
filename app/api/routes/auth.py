"""鉴权路由：注册、登录、当前用户；Web Cookie 会话（web-login/web-logout/csrf）。"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.core.web_auth import (
    clear_session_cookies,
    generate_csrf_token,
    set_csrf_cookie,
    set_session_cookie,
)
from app.db.session import get_db
from app.models import Membership, User
from app.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _issue_token(db: Session, user: User) -> TokenOut:
    if not user.membership:
        db.add(Membership(user_id=user.id, plan="free", is_active=False))
        db.commit()
    token = create_access_token(user.id, extra={"role": user.role})
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


def _ensure_membership(db: Session, user: User) -> None:
    """首次登录自动建 free Membership（与 native _issue_token 同一逻辑）。"""
    if not user.membership:
        db.add(Membership(user_id=user.id, plan="free", is_active=False))
        db.commit()


def _authenticate(db: Session, body: LoginIn) -> User:
    """校验邮箱/密码，返回有效用户；凭据错误或停用抛 401/403（与 native login 一致）。"""
    user = db.scalar(select(User).where(User.email == body.email))
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")
    return user


@router.post("/register", response_model=TokenOut)
@limiter.limit(settings.rate_limit_register)
def register(request: Request, body: RegisterIn, db: Session = Depends(get_db)):
    existing = db.scalar(select(User).where(User.email == body.email))
    if existing:
        raise HTTPException(status_code=400, detail="该邮箱已注册")
    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        nickname=body.nickname,
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _issue_token(db, user)


@router.post("/login", response_model=TokenOut)
@limiter.limit(settings.rate_limit_login)
def login(request: Request, body: LoginIn, db: Session = Depends(get_db)):
    user = _authenticate(db, body)
    return _issue_token(db, user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


# ---------- Web Cookie 会话（ADR-4，与 Bearer 共存）----------


def _issue_web_session(db: Session, user: User, response: Response) -> dict:
    """签发与 native 完全相同的 JWT，但放进 HttpOnly cookie 而非响应体；
    同时下发新的 CSRF token（双提交 cookie）。返回最小用户信息。"""
    _ensure_membership(db, user)
    token = create_access_token(user.id, extra={"role": user.role})
    set_session_cookie(response, token)
    csrf = generate_csrf_token()
    set_csrf_cookie(response, csrf)
    return {"id": user.id, "email": user.email}


@router.post("/web-login")
@limiter.limit(settings.rate_limit_login)
def web_login(
    request: Request,
    body: LoginIn,
    response: Response,
    db: Session = Depends(get_db),
):
    """Web 登录：校验通过后下发 HttpOnly 的 ff_session 与可读 csrftoken，
    响应体仅返回最小用户信息（不含 token 字符串）。

    与 /login 同一凭据校验逻辑；失败行为/限流保持一致。成功后总是轮换 CSRF token。
    """
    user = _authenticate(db, body)
    return _issue_web_session(db, user, response)


@router.post("/web-logout")
def web_logout(response: Response):
    """清除 ff_session 与 csrftoken（set-cookie 过期）。无需要求已登录，
    以便前端在 cookie 状态不明时也能干净登出。"""
    clear_session_cookies(response)
    # 204：成功但无响应体；delete_cookie 的 Set-Cookie 头仍会下发。
    response.status_code = 204
    return response


@router.get("/csrf")
def csrf(response: Response):
    """下发/轮换 CSRF token。进入登录页或会话建立前先调用，
    供前端从可读 cookie 读取并在写操作回填 X-CSRF-Token。"""
    token = generate_csrf_token()
    set_csrf_cookie(response, token)
    return {"csrf": token}
