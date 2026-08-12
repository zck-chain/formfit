"""Web 管理后台路由：登录、看板、用户、订阅、动作库管理。"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.admin_auth import COOKIE_NAME, create_session, read_session_payload
from app.core.config import BASE_DIR, settings
from app.core.security import verify_password
from app.db.session import get_db
from app.models import Exercise, Membership, Plan, User
from app.models.admin_audit import ADMIN_ACTIONS
from app.services import admin_audit, admin_service, exercise_service as svc

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
    """解析 session cookie：签名/时效有效且用户存在、为 admin、未停用、
    session_version 一致（未被服务端吊销）才返回该用户。"""
    payload = read_session_payload(request.cookies.get(COOKIE_NAME))
    if not payload:
        return None
    uid, ver = payload
    user = db.get(User, uid)
    if not user or user.role != "admin" or not user.is_active:
        return None
    if user.session_version != ver:
        # 服务端已吊销（登出/改密），cookie 失效
        return None
    return user


def require_admin(request: Request, db: Session) -> User:
    user = _current_admin(request, db)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})
    return user


def require_admin_html(request: Request, db: Session) -> User:
    """后台页面鉴权：

    - 持有有效 admin session 且为管理员 → 返回该用户。
    - 携带合法签名的 session cookie 但不是管理员（普通用户/已停用/版本不匹配）→ 403。
    - 未登录或 cookie 无效/过期 → 303 跳转登录页。

    与所有后台页共用的 ``require_admin`` 相比，本方法把「已登录但越权」与
    「未登录」区分开：审计页等敏感页面需要对越权访问显式返回 403，而不是
    静默重定向到登录页。
    """
    user = _current_admin(request, db)
    if user:
        return user
    payload = read_session_payload(request.cookies.get(COOKIE_NAME))
    if payload:
        # 合法签名会话，但身份不满足管理员 → 越权
        raise HTTPException(status_code=403, detail="需要管理员权限")
    raise HTTPException(status_code=303, headers={"Location": "/admin/login"})


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
    token = create_session(user.id, user.session_version)
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.admin_session_max_age_seconds,
    )
    return resp


@router.post("/admin/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    # 服务端吊销：递增 session_version，使该管理员已签发的 cookie 全部失效
    admin = _current_admin(request, db)
    if admin:
        admin.session_version += 1
        db.commit()
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
def toggle_user(
    user_id: int,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin":
        # 管理员账号不得被停/启用，防止越权或自锁。
        raise HTTPException(status_code=403, detail="不能操作管理员")

    action = "toggle_user"
    replay = admin_audit.is_replay(
        db,
        admin_id=admin.id,
        action=action,
        target_user_id=user_id,
        idempotency_key=idempotency_key,
    )
    before = admin_audit.snapshot_user(user)
    if replay:
        # 幂等命中：不重复翻转，只记一条命中审计（保留留痕，不改变状态）。
        admin_audit.record_event(
            db,
            admin_id=admin.id,
            action=action,
            target_user_id=user_id,
            before=before,
            after={**before, "idempotency_replay": True},
            reason=None,
            idempotency_key=idempotency_key,
        )
        db.commit()
        return RedirectResponse("/admin/users", status_code=303)

    user.is_active = not user.is_active
    db.flush()
    after = admin_audit.snapshot_user(user)
    admin_audit.record_event(
        db,
        admin_id=admin.id,
        action=action,
        target_user_id=user_id,
        before=before,
        after=after,
        reason=None,
        idempotency_key=idempotency_key,
    )
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


def _get_non_admin_target(db: Session, user_id: int) -> User:
    """取目标用户；不存在 → 404，目标为管理员 → 403（禁止管理员间互相操作）。"""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin":
        raise HTTPException(status_code=403, detail="不能操作管理员")
    return user


@router.post("/admin/membership/{user_id}")
def grant_membership(
    user_id: int,
    request: Request,
    plan: str = Form("pro"),
    days: int | None = Form(None),
    reason: str | None = Form(None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)
    user = _get_non_admin_target(db, user_id)

    reason = (reason or "").strip()
    if not reason:
        # 事由必填：所有人工发放必须可追溯。
        raise HTTPException(status_code=400, detail="发放会员必须填写 reason（操作事由）")
    if plan not in ("free", "pro"):
        raise HTTPException(status_code=400, detail="plan 仅支持 free / pro")

    action = "grant_membership"
    m = user.membership
    before = admin_audit.snapshot_membership(m)

    replay = admin_audit.is_replay(
        db,
        admin_id=admin.id,
        action=action,
        target_user_id=user_id,
        idempotency_key=idempotency_key,
    )
    if replay:
        admin_audit.record_event(
            db,
            admin_id=admin.id,
            action=action,
            target_user_id=user_id,
            before=before,
            after={**before, "idempotency_replay": True},
            reason=reason,
            idempotency_key=idempotency_key,
        )
        db.commit()
        return RedirectResponse("/admin/membership", status_code=303)

    if not m:
        m = Membership(user_id=user.id)
        db.add(m)
    now = datetime.now(timezone.utc)
    m.plan = plan
    m.is_active = plan == "pro"
    m.start_at = now
    if plan == "pro":
        # days 为空或 0 表示永久：expire_at 置空（is_membership_active 对 pro 永久需特殊判定，
        # 见下）。days > 0 则按天到期。
        if days and days > 0:
            m.expire_at = now + timedelta(days=days)
        else:
            m.expire_at = None
    else:
        # 降级回 free：立即到期。
        m.expire_at = now

    db.flush()
    after = admin_audit.snapshot_membership(m)
    admin_audit.record_event(
        db,
        admin_id=admin.id,
        action=action,
        target_user_id=user_id,
        before=before,
        after=after,
        reason=reason,
        idempotency_key=idempotency_key,
    )
    db.commit()
    return RedirectResponse("/admin/membership", status_code=303)


@router.post("/admin/membership/{user_id}/revoke")
def revoke_membership(
    user_id: int,
    request: Request,
    reason: str | None = Form(None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    """收回 PRO：不物理删除会员行，而是置 is_active=false 并把 expire_at 设为当前时间，
    同时写审计留痕（before/after 快照），支持撤销追溯。"""
    admin = require_admin(request, db)
    user = _get_non_admin_target(db, user_id)

    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="收回会员必须填写 reason（操作事由）")

    action = "revoke_membership"
    m = user.membership
    before = admin_audit.snapshot_membership(m)

    replay = admin_audit.is_replay(
        db,
        admin_id=admin.id,
        action=action,
        target_user_id=user_id,
        idempotency_key=idempotency_key,
    )
    if replay:
        admin_audit.record_event(
            db,
            admin_id=admin.id,
            action=action,
            target_user_id=user_id,
            before=before,
            after={**before, "idempotency_replay": True},
            reason=reason,
            idempotency_key=idempotency_key,
        )
        db.commit()
        return RedirectResponse("/admin/membership", status_code=303)

    now = datetime.now(timezone.utc)
    if not m:
        # 本就没有会员行：建一条 free 占位并立即失活，仍写审计记录这次收回动作。
        m = Membership(
            user_id=user.id,
            plan="free",
            is_active=False,
            start_at=now,
            expire_at=now,
        )
        db.add(m)
    else:
        m.is_active = False
        m.expire_at = now
        m.plan = "free"

    db.flush()
    after = admin_audit.snapshot_membership(m)
    admin_audit.record_event(
        db,
        admin_id=admin.id,
        action=action,
        target_user_id=user_id,
        before=before,
        after=after,
        reason=reason,
        idempotency_key=idempotency_key,
    )
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


# ---------- 操作审计 ----------
def _parse_dt(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    """解析查询参数中的时间。

    支持完整 ISO（``2026-08-12T08:00:00``）或仅日期 ``2026-08-12``；
    仅日期时，start 取当日 00:00，end 取当日 23:59:59，便于按天筛选。
    解析失败抛 400。naive 时间视为 UTC。
    """
    if not value:
        return None
    try:
        if "T" in value or " " in value:
            dt = datetime.fromisoformat(value)
        else:
            d = datetime.strptime(value, "%Y-%m-%d")
            if end_of_day:
                dt = d.replace(hour=23, minute=59, second=59, microsecond=999999)
            else:
                dt = d
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"无法解析时间参数: {value}")


@router.get("/admin/audit", response_class=HTMLResponse)
def audit_page(
    request: Request,
    action: str | None = None,
    admin_id: int | None = None,
    target_user_id: int | None = None,
    start: str | None = None,
    end: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """管理员操作审计查看页：分页 + action/操作者/目标/时间范围过滤。

    只读，不改变任何业务状态；序列化走白名单（admin_audit.serialize_event），
    不输出密码哈希/密钥/Cookie/Authorization。
    """
    admin = require_admin_html(request, db)

    if action and action not in ADMIN_ACTIONS:
        raise HTTPException(status_code=400, detail="action 取值非法")

    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end, end_of_day=True)
    if start_dt and end_dt and start_dt > end_dt:
        raise HTTPException(status_code=400, detail="start 不能晚于 end")

    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    items, total = admin_audit.list_events(
        db,
        action=action,
        admin_id=admin_id,
        target_user_id=target_user_id,
        start=start_dt,
        end=end_dt,
        page=page,
        page_size=page_size,
    )
    total_pages = (total + page_size - 1) // page_size

    # 保留当前过滤条件到分页/翻页链接
    query = {
        "action": action or "",
        "admin_id": admin_id or "",
        "target_user_id": target_user_id or "",
        "start": start or "",
        "end": end or "",
        "page_size": page_size,
    }

    return templates.TemplateResponse(
        request,
        "admin/audit.html",
        {
            "admin": admin,
            "active": "audit",
            "user_count": _user_count(db),
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "actions": ADMIN_ACTIONS,
            "action_labels": admin_audit.ACTION_ZH,
            "query": query,
        },
    )
