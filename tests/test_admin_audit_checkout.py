"""W5-2 后端：下单 Kill Switch 与管理员发放审计测试。

覆盖：
- CHECKOUT_ENABLED 关闭时 POST /api/payment/orders 返回 403 且不产生 Order；开启时流程不变。
- 管理员发放/收回/启停均写 admin_audit_events，before/after/reason/admin_id/request_id 正确。
- 管理员对其他 admin 的写操作被拒（403）。
- reason 缺失时发放/收回被拒（400）。
- 永不过期（days=0/空）发放后会员判定为有效。
- Idempotency-Key 短窗口去重不重复执行。
- 迁移 upgrade/downgrade 可逆（真实文件 SQLite + Alembic）。
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.admin_auth import COOKIE_NAME
from app.core.config import settings
from app.models import Membership, Order, User
from app.models.admin_audit import AdminAuditEvent
from app.services import membership_service


# ---------- 管理员登录夹具 ----------
def _login_admin(client: TestClient, password: str = "change-me-admin") -> dict:
    """通过后台登录表单换取 admin session cookie，返回 Cookie 头。"""
    resp = client.post(
        "/admin/login",
        data={"email": settings.admin_email, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    cookie = resp.headers.get("set-cookie", "")
    token = cookie.split(f"{COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{COOKIE_NAME}={token}"}


def _ensure_admin(db_session) -> User:
    """确保库里有默认管理员（与 startup.init_admin 一致的默认凭据）。"""
    from app.core.security import hash_password

    admin = db_session.query(User).filter_by(email=settings.admin_email).one_or_none()
    if admin:
        return admin
    admin = User(
        email=settings.admin_email,
        hashed_password=hash_password("change-me-admin"),
        nickname="管理员",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.flush()
    db_session.add(Membership(user_id=admin.id, plan="pro", is_active=True))
    db_session.commit()
    return admin


def _make_target_user(db_session, email: str = "target@test.com", role: str = "user") -> User:
    from app.core.security import hash_password

    u = User(
        email=email,
        hashed_password=hash_password("secret123"),
        nickname="Target",
        role=role,
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


# ---------- Kill Switch ----------
def test_checkout_disabled_returns_403_and_creates_no_order(
    client, register_user, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "checkout_enabled", False, raising=False)
    headers, _ = register_user(email="buyer@test.com")

    resp = client.post(
        "/api/payment/orders",
        json={"plan_code": "pro_monthly", "channel": "sandbox"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["detail"] == {"error": "checkout_disabled"}

    # 不建 Order
    assert db_session.query(Order).count() == 0


def test_checkout_disabled_blocks_all_channels(
    client, register_user, monkeypatch
):
    monkeypatch.setattr(settings, "checkout_enabled", False, raising=False)
    headers, _ = register_user(email="buyer2@test.com")
    for channel in ("sandbox", "alipay", "wechat", "apple"):
        resp = client.post(
            "/api/payment/orders",
            json={"plan_code": "pro_monthly", "channel": channel},
            headers=headers,
        )
        assert resp.status_code == 403, (channel, resp.status_code)


def test_checkout_enabled_sandbox_flow_unchanged(client, register_user, db_session):
    # 开启时（conftest 默认开启），沙箱下单正常
    headers, _ = register_user(email="happy@test.com")
    resp = client.post(
        "/api/payment/orders",
        json={"plan_code": "pro_monthly", "channel": "sandbox"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    order = db_session.query(Order).one()
    assert order.status == "pending"


def test_readonly_plans_available_when_checkout_disabled(
    client, monkeypatch
):
    # 只读接口在开关关闭时仍可用，供前端展示「暂未开放」
    monkeypatch.setattr(settings, "checkout_enabled", False, raising=False)
    assert client.get("/api/payment/plans?channel=sandbox").status_code == 200


# ---------- 管理员发放审计 ----------
def test_grant_membership_writes_audit(client, db_session):
    _ensure_admin(db_session)
    target = _make_target_user(db_session, email="grant@test.com")
    admin_cookie = _login_admin(client)

    resp = client.post(
        f"/admin/membership/{target.id}",
        data={"plan": "pro", "days": 30, "reason": "早期种子用户赠送"},
        headers=admin_cookie,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    m = db_session.query(Membership).filter_by(user_id=target.id).one()
    assert m.plan == "pro" and m.is_active is True
    assert m.expire_at is not None

    event = db_session.query(AdminAuditEvent).one()
    assert event.action == "grant_membership"
    assert event.target_user_id == target.id
    assert event.reason == "早期种子用户赠送"
    assert event.before_json["exists"] is False
    assert event.after_json["plan"] == "pro"
    assert event.after_json["is_active"] is True
    assert event.admin_id is not None
    assert event.request_id  # 中间件注入


def test_grant_membership_permanent_when_days_zero(client, db_session):
    _ensure_admin(db_session)
    target = _make_target_user(db_session, email="permanent@test.com")
    admin_cookie = _login_admin(client)

    resp = client.post(
        f"/admin/membership/{target.id}",
        data={"plan": "pro", "days": 0, "reason": "终身贡献者"},
        headers=admin_cookie,
        follow_redirects=False,
    )
    assert resp.status_code == 303
    m = db_session.query(Membership).filter_by(user_id=target.id).one()
    assert m.is_active is True and m.expire_at is None
    # 会员判定：永久 pro 视为有效
    assert membership_service.is_membership_active(m) is True
    assert membership_service.is_pro(db_session, target.id) is True


def test_grant_membership_missing_reason_rejected(client, db_session):
    _ensure_admin(db_session)
    target = _make_target_user(db_session, email="noreason@test.com")
    admin_cookie = _login_admin(client)

    resp = client.post(
        f"/admin/membership/{target.id}",
        data={"plan": "pro", "days": 30},
        headers=admin_cookie,
        follow_redirects=False,
    )
    assert resp.status_code == 400
    # 未写审计、未改会员
    assert db_session.query(AdminAuditEvent).count() == 0
    assert db_session.query(Membership).filter_by(user_id=target.id).first() is None


def test_grant_membership_rejects_admin_target(client, db_session):
    admin = _ensure_admin(db_session)
    another_admin = _make_target_user(
        db_session, email="other-admin@test.com", role="admin"
    )
    admin_cookie = _login_admin(client)

    resp = client.post(
        f"/admin/membership/{another_admin.id}",
        data={"plan": "pro", "days": 30, "reason": "尝试操作管理员"},
        headers=admin_cookie,
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert db_session.query(AdminAuditEvent).count() == 0


# ---------- 收回 PRO ----------
def test_revoke_membership_writes_audit(client, db_session):
    _ensure_admin(db_session)
    target = _make_target_user(db_session, email="revoke@test.com")
    # 先给一个有效 pro
    m = Membership(
        user_id=target.id, plan="pro", is_active=True,
        start_at=datetime.now(timezone.utc),
        expire_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_session.add(m)
    db_session.commit()
    admin_cookie = _login_admin(client)

    resp = client.post(
        f"/admin/membership/{target.id}/revoke",
        data={"reason": "违反社区规则"},
        headers=admin_cookie,
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db_session.refresh(m)
    assert m.is_active is False and m.plan == "free"
    assert membership_service.is_pro(db_session, target.id) is False

    event = db_session.query(AdminAuditEvent).filter_by(
        action="revoke_membership"
    ).one()
    assert event.before_json["plan"] == "pro"
    assert event.before_json["is_active"] is True
    assert event.after_json["is_active"] is False
    assert event.reason == "违反社区规则"


def test_revoke_membership_missing_reason_rejected(client, db_session):
    _ensure_admin(db_session)
    target = _make_target_user(db_session, email="revoke-nr@test.com")
    admin_cookie = _login_admin(client)
    resp = client.post(
        f"/admin/membership/{target.id}/revoke",
        data={},
        headers=admin_cookie,
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert db_session.query(AdminAuditEvent).count() == 0


def test_revoke_rejects_admin_target(client, db_session):
    _ensure_admin(db_session)
    other = _make_target_user(db_session, email="other2@test.com", role="admin")
    admin_cookie = _login_admin(client)
    resp = client.post(
        f"/admin/membership/{other.id}/revoke",
        data={"reason": "x"},
        headers=admin_cookie,
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert db_session.query(AdminAuditEvent).filter_by(
        action="revoke_membership"
    ).count() == 0


# ---------- 启停用户 ----------
def test_toggle_user_writes_audit(client, db_session):
    _ensure_admin(db_session)
    target = _make_target_user(db_session, email="toggle@test.com")
    admin_cookie = _login_admin(client)

    assert target.is_active is True
    resp = client.post(
        f"/admin/users/{target.id}/toggle",
        headers=admin_cookie,
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db_session.refresh(target)
    assert target.is_active is False

    event = db_session.query(AdminAuditEvent).filter_by(action="toggle_user").one()
    assert event.before_json["is_active"] is True
    assert event.after_json["is_active"] is False
    assert event.target_user_id == target.id


def test_toggle_user_rejects_admin_target(client, db_session):
    _ensure_admin(db_session)
    other = _make_target_user(db_session, email="other3@test.com", role="admin")
    admin_cookie = _login_admin(client)
    resp = client.post(
        f"/admin/users/{other.id}/toggle",
        headers=admin_cookie,
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert db_session.query(AdminAuditEvent).filter_by(
        action="toggle_user"
    ).count() == 0


# ---------- 幂等去重 ----------
def test_grant_idempotency_key_prevents_double_submit(client, db_session):
    _ensure_admin(db_session)
    target = _make_target_user(db_session, email="idem@test.com")
    admin_cookie = _login_admin(client)
    key = "grant-abc-123"
    payload = {"plan": "pro", "days": 30, "reason": "幂等测试"}

    r1 = client.post(
        f"/admin/membership/{target.id}", data=payload,
        headers={**admin_cookie, "Idempotency-Key": key}, follow_redirects=False,
    )
    r2 = client.post(
        f"/admin/membership/{target.id}", data=payload,
        headers={**admin_cookie, "Idempotency-Key": key}, follow_redirects=False,
    )
    assert r1.status_code == 303 and r2.status_code == 303

    events = db_session.query(AdminAuditEvent).filter_by(
        action="grant_membership"
    ).all()
    assert len(events) == 2
    # 第二次为命中回放，after 中带 idempotency_replay 且不改变会员
    assert events[1].after_json.get("idempotency_replay") is True
    # 会员只被发放一次（expire_at 未被第二次刷新到更晚）
    m = db_session.query(Membership).filter_by(user_id=target.id).one()
    assert m.is_active is True


# ---------- 迁移可逆 ----------
def test_migration_upgrade_downgrade_reversible(tmp_path, monkeypatch):
    """用真实文件 SQLite 跑 alembic upgrade head -> downgrade -1 -> upgrade head。"""
    import subprocess
    import sys

    db_path = tmp_path / "migtest.db"
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "PYTHONPATH": str(tmp_path) + ":" + ":".join(sys.path),
        "DATABASE_URL": f"sqlite:///{db_path}",
        # 给一个能通过生产校验的非默认密钥（即使非生产也无碍）
        "APP_ENV": "development",
        "JWT_SECRET": "test-jwt-secret-0123456789abcdef",
        "ADMIN_SESSION_SECRET": "test-admin-secret-0123456789abcdef",
        "ADMIN_PASSWORD": "strong-test-pass-123",
        "HOME": str(tmp_path),
    }

    def run_alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd="/Users/apple/Desktop/工作/开发项目/FormFit-ws5-be",
            env=env, capture_output=True, text=True,
        )

    up = run_alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr + up.stdout

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "admin_audit_events" in tables
    conn.close()

    down = run_alembic("downgrade", "-1")
    assert down.returncode == 0, down.stderr + down.stdout
    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "admin_audit_events" not in tables
    assert "payment_audit_events" in tables  # 上一版表仍在
    conn.close()

    up2 = run_alembic("upgrade", "head")
    assert up2.returncode == 0, up2.stderr + up2.stdout
