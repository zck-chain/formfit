"""PRO 会员门控测试：free 被拒（402），pro 通过，支付沙箱链路后可调用。"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Membership


def _grant_pro(db_session, user_id: int, days: int = 30) -> Membership:
    m = db_session.query(Membership).filter_by(user_id=user_id).one()
    now = datetime.now(timezone.utc)
    m.plan = "pro"
    m.is_active = True
    m.start_at = now
    m.expire_at = now + timedelta(days=days)
    m.payment_channel = "sandbox"
    db_session.commit()
    return m


# ---------- free 用户被拒 ----------
def test_free_user_assess_blocked(client, register_user):
    headers, _ = register_user()
    # 任意图片请求都会在进入处理前被门控拦下（402）
    resp = client.post(
        "/api/fitness/assess",
        headers=headers,
        files={"file": ("a.jpg", b"fakepng", "image/png")},
    )
    assert resp.status_code == 402, resp.text
    body = resp.json()["detail"]
    assert body["error"] == "pro_required"
    assert body["feature"] == "assess"
    assert body["upgrade_hint"] == "/api/payment/plans"


def test_free_user_generate_plan_blocked(client, register_user):
    headers, _ = register_user()
    resp = client.post(
        "/api/fitness/plans/generate",
        headers=headers,
        json={"goal": "增肌"},
    )
    assert resp.status_code == 402, resp.text
    assert resp.json()["detail"]["feature"] == "generate_plan"


def test_anonymous_blocked(client):
    # 未登录先走认证 -> 401（门控依赖于登录用户）
    resp = client.post("/api/fitness/plans/generate", json={"goal": "增肌"})
    assert resp.status_code == 401


# ---------- GET /api/membership 会员态查询 ----------
def test_membership_free_default(client, register_user):
    headers, _ = register_user()
    resp = client.get("/api/membership", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["plan"] == "free"
    assert data["is_active"] is False
    assert data["is_pro"] is False
    assert data["features_locked"] is True
    assert data["expire_at"] is None


def test_membership_anonymous_401(client):
    assert client.get("/api/membership").status_code == 401


def test_membership_reflects_pro_after_payment(client, register_user, db_session):
    import hashlib
    import hmac

    from app.core.config import settings

    headers, user = register_user()
    _grant_pro(db_session, user["id"])

    resp = client.get("/api/membership", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan"] == "pro"
    assert data["is_active"] is True
    assert data["is_pro"] is True
    assert data["features_locked"] is False
    assert data["expire_at"] is not None
    assert data["payment_channel"] is not None


def test_membership_expired_shows_locked(client, register_user, db_session):
    headers, user = register_user()
    _grant_pro(db_session, user["id"], days=-1)
    data = client.get("/api/membership", headers=headers).json()
    # 过期 pro 视为非有效，功能锁定（plan 字段仍为 pro，但 is_active/is_pro 为 false）
    assert data["is_active"] is False
    assert data["is_pro"] is False
    assert data["features_locked"] is True


# ---------- pro 用户通过 ----------
def test_pro_user_generate_plan_passes(client, register_user, db_session, monkeypatch):
    headers, user = register_user()
    _grant_pro(db_session, user["id"])

    # mock 掉 AI planner，避免外网调用
    async def _fake_generate(db, profile, assessment):
        return {"title": "测试计划", "weeks": 4, "days_per_week": 3, "items": []}

    monkeypatch.setattr("app.agent.planner.generate_plan", _fake_generate)

    resp = client.post(
        "/api/fitness/plans/generate",
        headers=headers,
        json={"goal": "增肌"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "测试计划"


def test_pro_user_assess_passes(client, register_user, db_session, monkeypatch, tmp_path):
    headers, user = register_user()
    _grant_pro(db_session, user["id"])

    async def _fake_assess(path, **kwargs):
        return {
            "direction": "gain",
            "body_type": "ectomorph",
            "summary": "测试评估",
            "observed": [],
            "safety_notes": None,
        }

    monkeypatch.setattr("app.agent.qwen_vl_client.assess_body", _fake_assess)

    resp = client.post(
        "/api/fitness/assess",
        headers=headers,
        files={"file": ("a.jpg", b"fakepng", "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["direction"] == "gain"


# ---------- 过期 pro 视为 free ----------
def test_expired_pro_blocked(client, register_user, db_session):
    headers, user = register_user()
    _grant_pro(db_session, user["id"], days=-1)  # 已过期
    resp = client.post(
        "/api/fitness/plans/generate",
        headers=headers,
        json={"goal": "增肌"},
    )
    assert resp.status_code == 402


# ---------- 支付沙箱链路后即可调用被门控接口 ----------
def test_payment_then_gated_endpoint_passes(
    client, register_user, db_session, monkeypatch
):
    import hashlib
    import hmac

    from app.core.config import settings

    headers, user = register_user()

    # 下单
    order = client.post(
        "/api/payment/orders",
        json={"plan_code": "pro_monthly", "channel": "sandbox"},
        headers=headers,
    ).json()
    sb = order["pay_credential"]["sandbox"]
    amount = sb["amount_cents"]
    body = {
        "order_no": order["order_no"],
        "txn_id": sb["txn_id"],
        "status": "success",
        "amount_cents": amount,
        "currency": "CNY",
    }
    msg = f"{body['order_no']}.success.{amount}.{body['txn_id']}".encode()
    sig = hmac.new(settings.sandbox_secret.encode(), msg, hashlib.sha256).hexdigest()
    cb = client.post(
        "/api/payment/callback/sandbox",
        json=body,
        headers={"x-sandbox-signature": sig},
    )
    assert cb.status_code == 200, cb.text

    # 会员已开通，调用被门控的计划生成应放行
    async def _fake_generate(db, profile, assessment):
        return {"title": "付费后计划", "weeks": 4, "days_per_week": 3, "items": []}

    monkeypatch.setattr("app.agent.planner.generate_plan", _fake_generate)

    resp = client.post(
        "/api/fitness/plans/generate",
        headers=headers,
        json={"goal": "减脂"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "付费后计划"
