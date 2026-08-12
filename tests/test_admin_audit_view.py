"""W7-2：管理员后台操作审计查看页测试。

覆盖验收标准：
- 非管理员携带合法会话访问 GET /admin/audit → 403；未登录 → 303 跳登录；管理员 → 200。
- 分页：page/page_size 生效，total 正确，page_size 上限 100。
- 过滤：action / admin_id / target_user_id / 时间范围生效，非法 action/时间 → 400。
- 序列化白名单：响应不含密码哈希、密钥、Cookie、Authorization 等敏感字段，
  且只展示审计模型白名单字段。
"""
from datetime import datetime, timedelta, timezone

from app.core.admin_auth import COOKIE_NAME, create_session
from app.core.security import hash_password
from app.models import Membership, User
from app.models.admin_audit import AdminAuditEvent
from app.services import admin_audit


def _make_user(db_session, email, role="user", active=True):
    u = User(
        email=email,
        hashed_password=hash_password("secret123"),
        nickname=email.split("@")[0],
        role=role,
        is_active=active,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


def _cookie_for(user: User) -> dict:
    token = create_session(user.id, user.session_version)
    return {"Cookie": f"{COOKIE_NAME}={token}"}


def _seed_event(db_session, *, admin_id, action, target, days_ago=0, reason="测试事由"):
    ev = AdminAuditEvent(
        admin_id=admin_id,
        action=action,
        target_user_id=target,
        before_json={"exists": False},
        after_json={"exists": True, "plan": "pro", "is_active": True},
        reason=reason,
        request_id=f"req-{action}-{target}-{days_ago}",
        idempotency_key=None,
    )
    # 直接设置 created_at 以便测试时间过滤
    if days_ago:
        ev.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db_session.add(ev)
    db_session.commit()
    return ev


# ---------- 鉴权 ----------
def test_audit_requires_admin(client, db_session):
    # 未登录 → 303 跳登录
    resp = client.get("/admin/audit", follow_redirects=False)
    assert resp.status_code == 303
    assert "/admin/login" in resp.headers["location"]


def test_audit_non_admin_forbidden(client, db_session):
    # 普通用户持有合法签名会话 → 403（不是重定向到登录）
    normal = _make_user(db_session, "normal@test.com")
    resp = client.get("/admin/audit", headers=_cookie_for(normal), follow_redirects=False)
    assert resp.status_code == 403


def test_audit_deactivated_admin_forbidden(client, db_session):
    # 已停用管理员 → 403（cookie 签名有效但身份不满足）
    admin = _make_user(db_session, "dead-admin@test.com", role="admin", active=False)
    db_session.add(Membership(user_id=admin.id, plan="pro", is_active=True))
    db_session.commit()
    resp = client.get("/admin/audit", headers=_cookie_for(admin), follow_redirects=False)
    assert resp.status_code == 403


def test_audit_admin_ok(client, db_session):
    admin = _make_user(db_session, "boss@test.com", role="admin")
    db_session.add(Membership(user_id=admin.id, plan="pro", is_active=True))
    db_session.commit()
    resp = client.get("/admin/audit", headers=_cookie_for(admin), follow_redirects=False)
    assert resp.status_code == 200
    assert "操作审计".encode() in resp.content


# ---------- 分页 ----------
def test_audit_pagination(client, db_session):
    admin = _make_user(db_session, "boss2@test.com", role="admin")
    db_session.add(Membership(user_id=admin.id, plan="pro", is_active=True))
    db_session.commit()
    target = _make_user(db_session, "t@test.com")
    for i in range(5):
        _seed_event(db_session, admin_id=admin.id, action="grant_membership",
                    target=target.id, reason=f"r{i}")

    cookie = _cookie_for(admin)
    r1 = client.get("/admin/audit?page=1&page_size=2", headers=cookie)
    assert r1.status_code == 200
    assert "共 5 条".encode() in r1.content
    # 第一页有 2 行，第二页链接存在
    assert "第 1 / 3 页".encode() in r1.content


def test_audit_page_size_capped(client, db_session):
    admin = _make_user(db_session, "boss3@test.com", role="admin")
    db_session.add(Membership(user_id=admin.id, plan="pro", is_active=True))
    db_session.commit()
    # 越界 page_size 被夹到 100，不应 500
    r = client.get("/admin/audit?page_size=9999", headers=_cookie_for(admin))
    assert r.status_code == 200


# ---------- 过滤 ----------
def test_audit_filter_by_action(client, db_session):
    admin = _make_user(db_session, "boss4@test.com", role="admin")
    db_session.add(Membership(user_id=admin.id, plan="pro", is_active=True))
    db_session.commit()
    target = _make_user(db_session, "t4@test.com")
    _seed_event(db_session, admin_id=admin.id, action="grant_membership", target=target.id)
    _seed_event(db_session, admin_id=admin.id, action="revoke_membership", target=target.id)
    _seed_event(db_session, admin_id=admin.id, action="toggle_user", target=target.id)

    cookie = _cookie_for(admin)
    r = client.get("/admin/audit?action=grant_membership", headers=cookie)
    assert r.status_code == 200
    body = r.content.decode()
    assert "共 1 条" in body
    # 只返回 grant 那一条：用各自行的 request_id 精确判定（下拉框也会列出动作名，不能据此判断）
    assert "req-grant_membership" in body
    assert "req-revoke_membership" not in body
    assert "req-toggle_user" not in body


def test_audit_filter_invalid_action_400(client, db_session):
    admin = _make_user(db_session, "boss5@test.com", role="admin")
    db_session.add(Membership(user_id=admin.id, plan="pro", is_active=True))
    db_session.commit()
    r = client.get("/admin/audit?action=drop_table", headers=_cookie_for(admin))
    assert r.status_code == 400


def test_audit_filter_by_admin_and_target(client, db_session):
    admin1 = _make_user(db_session, "a1@test.com", role="admin")
    admin2 = _make_user(db_session, "a2@test.com", role="admin")
    db_session.add_all([
        Membership(user_id=admin1.id, plan="pro", is_active=True),
        Membership(user_id=admin2.id, plan="pro", is_active=True),
    ])
    db_session.commit()
    t1 = _make_user(db_session, "t1@test.com")
    t2 = _make_user(db_session, "t2@test.com")
    _seed_event(db_session, admin_id=admin1.id, action="toggle_user", target=t1.id)
    _seed_event(db_session, admin_id=admin2.id, action="toggle_user", target=t2.id)

    # 按 admin 过滤
    items, total = admin_audit.list_events(db_session, admin_id=admin1.id)
    assert total == 1 and items[0]["admin_id"] == admin1.id
    # 按 target 过滤
    items, total = admin_audit.list_events(db_session, target_user_id=t2.id)
    assert total == 1 and items[0]["target_user_id"] == t2.id


def test_audit_filter_by_time_range(client, db_session):
    admin = _make_user(db_session, "boss6@test.com", role="admin")
    db_session.add(Membership(user_id=admin.id, plan="pro", is_active=True))
    db_session.commit()
    target = _make_user(db_session, "t6@test.com")
    _seed_event(db_session, admin_id=admin.id, action="grant_membership", target=target.id, days_ago=10)
    _seed_event(db_session, admin_id=admin.id, action="grant_membership", target=target.id, days_ago=2)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    items, total = admin_audit.list_events(db_session, start=week_ago, end=today)
    assert total == 1  # 只有 2 天前的那条


def test_audit_bad_time_param_400(client, db_session):
    admin = _make_user(db_session, "boss7@test.com", role="admin")
    db_session.add(Membership(user_id=admin.id, plan="pro", is_active=True))
    db_session.commit()
    r = client.get("/admin/audit?start=not-a-date", headers=_cookie_for(admin))
    assert r.status_code == 400


# ---------- 序列化白名单 / 敏感字段 ----------
def test_audit_serialize_whitelist_no_secrets(db_session):
    admin = _make_user(db_session, "ser-boss@test.com", role="admin")
    target = _make_user(db_session, "ser-target@test.com")
    ev = _seed_event(db_session, admin_id=admin.id, action="grant_membership",
                     target=target.id, reason="白名单测试")

    items, total = admin_audit.list_events(db_session)
    assert total == 1
    item = items[0]

    allowed = {
        "id", "created_at", "admin_id", "admin_email", "action", "action_label",
        "target_user_id", "target_email", "reason", "before", "after",
        "request_id", "idempotency_key",
    }
    assert set(item.keys()) == allowed

    # 操作者/目标用户对象不得整对象泄露：邮箱是唯一附带字段，绝不能出现密码哈希等
    blob = repr(item).lower()
    for secret in ("hashed_password", "password", "secret", "authorization",
                   "cookie", "session_version", "reset_token"):
        assert secret not in blob, f"序列化结果疑似泄露敏感字段: {secret}"

    # before/after 仅为白名单快照字段
    assert set(item["before"].keys()) <= {"exists", "plan", "is_active", "start_at", "expire_at", "role", "idempotency_replay"}
    assert item["admin_email"] == admin.email
    assert item["target_email"] == target.email
    assert item["reason"] == "白名单测试"


def test_audit_rendered_page_has_no_password_hashes(client, db_session):
    admin = _make_user(db_session, "boss8@test.com", role="admin")
    db_session.add(Membership(user_id=admin.id, plan="pro", is_active=True))
    target = _make_user(db_session, "t8@test.com")
    db_session.commit()
    _seed_event(db_session, admin_id=admin.id, action="grant_membership", target=target.id)

    r = client.get("/admin/audit", headers=_cookie_for(admin))
    body = r.content.decode().lower()
    assert "hashed_password" not in body
    assert admin.hashed_password.lower() not in body
    assert "authorization" not in body
