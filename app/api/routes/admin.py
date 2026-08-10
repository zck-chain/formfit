"""Web 管理后台路由：登录、看板、用户、订阅、动作库管理。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.admin_auth import COOKIE_NAME, create_session, read_session
from app.core.config import BASE_DIR, settings
from app.core.security import verify_password
from app.db.session import get_db
from app.models import Exercise, Membership, Plan, User
from app.services import admin_service, exercise_service as svc

router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _media_url(path: str) -> str:
    """数据集中 image/gif_url 形如 images/xxx.jpg → /media/exercises/images/xxx.jpg"""
    if not path:
        return ""
    return "/media/exercises/" + path


templates.env.filters["media_url"] = _media_url
# 暴露中英文映射给模板
templates.env.globals["target_zh"] = lambda v: svc.TARGET_ZH.get(v, v)
templates.env.globals["equip_zh"] = lambda v: svc.EQUIPMENT_ZH.get(v, v)


def _user_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User)) or 0


def _current_admin(request: Request, db: Session) -> User | None:
    uid = read_session(request.cookies.get(COOKIE_NAME))
    if not uid:
        return None
    user = db.get(User, uid)
    if user and user.role == "admin" and user.is_active:
        return user
    return None


def require_admin(request: Request, db: Session) -> User:
    user = _current_admin(request, db)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})
    return user


@router.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if _current_admin(request, db):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(
        request, "admin/login.html", {"error": None}
    )


@router.post("/admin/login")
def login_submit(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(password, user.hashed_password) or user.role != "admin":
        return templates.TemplateResponse(
            request,
            "admin/login.html",
            {"error": "邮箱或密码错误，或该账号非管理员"},
            status_code=401,
        )
    token = create_session(user.id)
    resp = RedirectResponse("/admin", status_code=303)
    # 生产环境走 HTTPS 时启用 secure；httponly 防 XSS 读取，samesite=lax 防 CSRF。
    resp.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=60 * 60 * 24 * 7,
        path="/",
    )
    return resp


@router.post("/admin/logout")
def logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ---------- 看板 ----------
@router.get("/admin", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    data = admin_service.overview(db)
    # 给 KPI 装载杆计算填充百分比（相对最大值归一化）
    k = data["kpis"]
    fills = {
        "total_users": 100,
        "pro_users": min(100, k["pro_users"] / max(k["total_users"], 1) * 100),
        "total_plans": min(100, k["total_plans"] / max(k["total_users"], 1) * 100),
        "total_assessments": min(100, k["total_assessments"] / max(k["total_users"], 1) * 100),
        "total_logs": min(100, k["total_logs"] / max(k["total_users"], 1) * 100),
    }
    recent_users = db.scalars(
        select(User).order_by(User.created_at.desc()).limit(8)
    ).all()
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "admin": admin, "active": "dashboard", "user_count": _user_count(db),
            "k": k, "fills": fills,
            "daily": data["daily_signups"],
            "directions": data["directions"],
            "recent_users": recent_users,
        },
    )


# ---------- 用户管理 ----------
@router.get("/admin/users", response_class=HTMLResponse)
def users_page(
    request: Request,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    stmt = select(User).order_by(User.created_at.desc())
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%"))
    users = db.scalars(stmt.limit(200)).all()
    # 带上会员信息
    result = []
    for u in users:
        result.append({"user": u, "membership": u.membership})
    return templates.TemplateResponse(
        request, "admin/users.html",
        {"admin": admin, "active": "users", "rows": result, "q": q or "", "user_count": _user_count(db)},
    )


@router.post("/admin/users/{user_id}/toggle")
def toggle_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    user = db.get(User, user_id)
    if not user or user.role == "admin":
        raise HTTPException(status_code=400, detail="不能操作管理员")
    user.is_active = not user.is_active
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


# ---------- 订阅管理 ----------
@router.get("/admin/membership", response_class=HTMLResponse)
def membership_page(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    rows = db.execute(
        select(User, Membership)
        .outerjoin(Membership, Membership.user_id == User.id)
        .order_by(User.created_at.desc())
        .limit(200)
    ).all()
    return templates.TemplateResponse(
        request, "admin/membership.html",
        {"admin": admin, "active": "membership", "rows": rows, "user_count": _user_count(db)},
    )


@router.post("/admin/membership/{user_id}")
def grant_membership(
    user_id: int,
    request: Request,
    plan: str = Form("pro"),
    days: int = Form(30),
    db: Session = Depends(get_db),
):
    require_admin(request, db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404)
    m = user.membership
    if not m:
        m = Membership(user_id=user.id)
        db.add(m)
    m.plan = plan
    m.is_active = plan == "pro"
    now = datetime.now(timezone.utc)
    m.start_at = now
    if plan == "pro":
        from datetime import timedelta
        m.expire_at = now + timedelta(days=days)
    else:
        m.expire_at = now
    db.commit()
    return RedirectResponse("/admin/membership", status_code=303)


# ---------- 动作库管理 ----------
@router.get("/admin/exercises", response_class=HTMLResponse)
def exercises_page(
    request: Request,
    category: str | None = None,
    equipment: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    from sqlalchemy import or_

    stmt = select(Exercise)
    if category:
        stmt = stmt.where(Exercise.category == category)
    if equipment:
        stmt = stmt.where(Exercise.equipment == equipment)
    if q:
        stmt = stmt.where(Exercise.name.ilike(f"%{q}%"))
    exercises = db.scalars(stmt.limit(120)).all()
    facets = svc.list_facets(db)
    return templates.TemplateResponse(
        request, "admin/exercises.html",
        {
            "admin": admin, "active": "exercises", "user_count": _user_count(db),
            "exercises": exercises, "facets": facets,
            "selected_cat": category or "", "selected_eq": equipment or "", "q": q or "",
        },
    )


@router.get("/admin/exercises/{exercise_id}", response_class=HTMLResponse)
def exercise_detail(
    exercise_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """单个动作详情：大图、目标/辅助肌、中文步骤。"""
    admin = require_admin(request, db)
    ex = svc.get_by_id(db, exercise_id)
    if not ex:
        raise HTTPException(status_code=404, detail="动作不存在")
    return templates.TemplateResponse(
        request, "admin/exercise_detail.html",
        {
            "admin": admin, "active": "exercises", "user_count": _user_count(db),
            "ex": ex,
        },
    )
