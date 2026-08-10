"""鉴权路由：注册、登录、当前用户。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
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


@router.post("/register", response_model=TokenOut)
def register(body: RegisterIn, db: Session = Depends(get_db)):
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
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email))
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")
    return _issue_token(db, user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
