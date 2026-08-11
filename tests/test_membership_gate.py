"""PRO 会员门控与免费额度测试。

PRO 不限次；free 用户体态评估与 AI 计划生成**共享**每月 5 次额度池（默认），
两功能合计第 6 次调用返回 402 quota_exhausted。
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import BodyAssessment, Membership, Plan
from app.core.config import settings


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


def _seed_assessments(db_session, user_id: int, n: int) -> None:
    for _ in range(n):
        db_session.add(
            BodyAssessment(
                user_id=user_id,
                media_path="uploads/x.jpg",
                media_type="image",
                summary="seed",
            )
        )
    db_session.commit()


def _seed_plans(db_session, user_id: int, n: int) -> None:
    for _ in range(n):
        db_session.add(Plan(user_id=user_id, title="seed", content={}))
    db_session.commit()


# ---------- 免费额度内放行 / 超额 402 ----------
def test_free_user_assess_quota_exhausted(client, register_user, db_session, monkeypatch):
    headers, user = register_user()
    _seed_assessments(db_session, user["id"], settings.free_quota_per_month)

    async def _fake_assess(path, **kwargs):  # pragma: no cover - 不应走到
        raise AssertionError("超额时不应进入评估逻辑")

    monkeypatch.setattr("app.agent.qwen_vl_client.assess_body", _fake_assess)

    resp = client.post(
        "/api/fitness/assess",
        headers=headers,
        files={"file": ("a.jpg", b"fakepng", "image/png")},
    )
    assert resp.status_code == 402, resp.text
    body = resp.json()["detail"]
    assert body["error"] == "quota_exhausted"
    assert body["feature"] == "assess"
    assert body["limit"] == settings.free_quota_per_month
    assert body["used"] == settings.free_quota_per_month
    assert body["upgrade_hint"] == "/api/payment/plans"
    assert "reset_at" in body


def test_free_user_generate_plan_quota_exhausted(client, register_user, db_session, monkeypatch):
    headers, user = register_user()
    _seed_plans(db_session, user["id"], settings.free_quota_per_month)

    async def _fake_generate(db, profile, assessment):  # pragma: no cover
        raise AssertionError("超额时不应进入计划生成逻辑")

    monkeypatch.setattr("app.agent.planner.generate_plan", _fake_generate)

    resp = client.post(
        "/api/fitness/plans/generate",
        headers=headers,
        json={"goal": "增肌"},
    )
    assert resp.status_code == 402, resp.text
    body = resp.json()["detail"]
    assert body["error"] == "quota_exhausted"
    assert body["feature"] == "generate_plan"


def test_free_user_first_assess_passes_quota_gate(
    client, register_user, monkeypatch, tmp_path
):
    """免费用户首次评估应通过门控（额度内），进入业务逻辑（mock AI 后返回 200）。"""
    headers, _ = register_user()

    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), (0, 0, 0)).save(buf, format="PNG")

    async def _fake_assess(path, **kwargs):
        return {
            "direction": "gain",
            "body_type": "ectomorph",
            "summary": "测试评估",
            "observed": [],
            "safety_notes": None,
        }

    monkeypatch.setattr("app.agent.qwen_vl_client.assess_body", _fake_assess)
    # 不真实落盘到 static/uploads，mock 掉写文件
    monkeypatch.setattr("pathlib.Path.write_bytes", lambda self, data: None)

    resp = client.post(
        "/api/fitness/assess",
        headers=headers,
        files={"file": ("a.png", buf.getvalue(), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    # 响应头带的是门控评估时（本次调用前）的共享池剩余：首次为满额
    assert resp.headers["X-Quota-Feature"] == "assess"
    assert resp.headers["X-Quota-Remaining"] == str(settings.free_quota_per_month)
    # 调用成功后已新增一条记录，/membership 共享池已用 1 次
    mem = client.get("/api/membership", headers=headers).json()
    assert mem["quota"]["scope"] == "shared"
    assert mem["quota"]["used"] == 1
    assert mem["quota"]["remaining"] == settings.free_quota_per_month - 1
    assert mem["quota"]["breakdown"]["assess"] == 1
    assert mem["quota"]["breakdown"]["generate_plan"] == 0


def test_free_user_first_generate_plan_passes_quota_gate(client, register_user, monkeypatch):
    headers, _ = register_user()

    async def _fake_generate(db, profile, assessment):
        return {"title": "免费额度内计划", "weeks": 4, "days_per_week": 3, "items": []}

    monkeypatch.setattr("app.agent.planner.generate_plan", _fake_generate)

    resp = client.post(
        "/api/fitness/plans/generate",
        headers=headers,
        json={"goal": "增肌"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "免费额度内计划"
    # 门控头反映本次调用前的共享池剩余（满额）；成功后 /membership 显示已用 1 次
    assert resp.headers["X-Quota-Remaining"] == str(settings.free_quota_per_month)
    mem = client.get("/api/membership", headers=headers).json()
    assert mem["quota"]["used"] == 1
    assert mem["quota"]["remaining"] == settings.free_quota_per_month - 1
    assert mem["quota"]["breakdown"]["generate_plan"] == 1


def test_shared_pool_mixed_usage_then_blocked(client, register_user, db_session, monkeypatch):
    """共享池：3 次 assess + 2 次 plan = 5，第 6 次无论 assess 还是 plan 都 402。"""
    headers, user = register_user()
    _seed_assessments(db_session, user["id"], 3)
    _seed_plans(db_session, user["id"], 2)

    async def _fake_generate(db, profile, assessment):  # pragma: no cover
        raise AssertionError("超额时不应进入计划生成逻辑")

    async def _fake_assess(path, **kwargs):  # pragma: no cover
        raise AssertionError("超额时不应进入评估逻辑")

    monkeypatch.setattr("app.agent.planner.generate_plan", _fake_generate)
    monkeypatch.setattr("app.agent.qwen_vl_client.assess_body", _fake_assess)

    # 第 6 次：plan 被 402，共享池 used=5
    resp = client.post(
        "/api/fitness/plans/generate", headers=headers, json={"goal": "减脂"}
    )
    assert resp.status_code == 402, resp.text
    body = resp.json()["detail"]
    assert body["error"] == "quota_exhausted"
    assert body["used"] == settings.free_quota_per_month
    assert body["feature"] == "generate_plan"

    # 第 6 次换成 assess 同样 402（同一池子）
    resp2 = client.post(
        "/api/fitness/assess",
        headers=headers,
        files={"file": ("a.jpg", b"fakepng", "image/png")},
    )
    assert resp2.status_code == 402
    assert resp2.json()["detail"]["feature"] == "assess"
    assert resp2.json()["detail"]["used"] == settings.free_quota_per_month


def test_shared_pool_mixed_within_limit_passes(client, register_user, db_session, monkeypatch):
    """共享池内混用：2 assess + 2 plan = 4，第 5 次（plan）仍放行。"""
    headers, user = register_user()
    _seed_assessments(db_session, user["id"], 2)
    _seed_plans(db_session, user["id"], 2)

    async def _fake_generate(db, profile, assessment):
        return {"title": "池内第5次", "weeks": 4, "days_per_week": 3, "items": []}

    monkeypatch.setattr("app.agent.planner.generate_plan", _fake_generate)

    resp = client.post(
        "/api/fitness/plans/generate", headers=headers, json={"goal": "增肌"}
    )
    assert resp.status_code == 200, resp.text
    # 门控时 used=4，剩余 1
    assert resp.headers["X-Quota-Remaining"] == "1"


def test_anonymous_blocked(client):
    # 未登录先走认证 -> 401（门控依赖于登录用户）
    resp = client.post("/api/fitness/plans/generate", json={"goal": "增肌"})
    assert resp.status_code == 401


# ---------- GET /api/membership 会员态与配额 ----------
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
    # 共享额度池字段
    q = data["quota"]
    assert q["scope"] == "shared"
    assert q["limit"] == settings.free_quota_per_month
    assert q["used"] == 0
    assert q["remaining"] == settings.free_quota_per_month
    assert q["reset_at"] is not None
    assert q["breakdown"] == {"assess": 0, "generate_plan": 0}


def test_membership_quota_reflects_usage(client, register_user, db_session):
    headers, user = register_user()
    _seed_assessments(db_session, user["id"], 3)
    _seed_plans(db_session, user["id"], 1)
    data = client.get("/api/membership", headers=headers).json()
    # 共享池：合计已用 4，剩余 1
    assert data["quota"]["used"] == 4
    assert data["quota"]["remaining"] == settings.free_quota_per_month - 4
    assert data["quota"]["breakdown"] == {"assess": 3, "generate_plan": 1}


def test_membership_pro_quota_unlimited(client, register_user, db_session):
    """PRO 用户 remaining 为 null（不限次），但仍展示已用次数与拆分。"""
    headers, user = register_user()
    _grant_pro(db_session, user["id"])
    _seed_assessments(db_session, user["id"], 99)
    data = client.get("/api/membership", headers=headers).json()
    assert data["is_pro"] is True
    assert data["features_locked"] is False
    assert data["quota"]["used"] == 99
    assert data["quota"]["remaining"] is None


def test_membership_anonymous_401(client):
    assert client.get("/api/membership").status_code == 401


def test_membership_reflects_pro_after_payment(client, register_user, db_session):
    import hashlib
    import hmac

    from app.core.config import settings as app_settings

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
    # PRO 不限次，不返回 X-Quota-Remaining 数值（剩余为无限语义，不写该头）
    assert "x-quota-remaining" not in {k.lower() for k in resp.headers.keys()}


def test_pro_user_assess_passes(client, register_user, db_session, monkeypatch, tmp_path):
    headers, user = register_user()
    _grant_pro(db_session, user["id"])

    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), (0, 0, 0)).save(buf, format="PNG")
    png_bytes = buf.getvalue()

    async def _fake_assess(path, **kwargs):
        return {
            "direction": "gain",
            "body_type": "ectomorph",
            "summary": "测试评估",
            "observed": [],
            "safety_notes": None,
        }

    monkeypatch.setattr("app.agent.qwen_vl_client.assess_body", _fake_assess)
    monkeypatch.setattr("pathlib.Path.write_bytes", lambda self, data: None)

    resp = client.post(
        "/api/fitness/assess",
        headers=headers,
        files={"file": ("a.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["direction"] == "gain"


# ---------- 过期 pro 视为 free（受额度约束）----------
def test_expired_pro_blocked_when_quota_exhausted(client, register_user, db_session):
    headers, user = register_user()
    _grant_pro(db_session, user["id"], days=-1)  # 已过期 → 按 free 计额度
    _seed_plans(db_session, user["id"], settings.free_quota_per_month)
    resp = client.post(
        "/api/fitness/plans/generate",
        headers=headers,
        json={"goal": "增肌"},
    )
    assert resp.status_code == 402
    assert resp.json()["detail"]["error"] == "quota_exhausted"


# ---------- 跨月重置（直接测计数函数，冻结时间）----------
def test_quota_resets_across_months(db_session, register_user):
    _, user = register_user()
    user_id = user["id"]
    from app.services import membership_service

    # 在"上个月"造 5 条评估记录
    now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
    last_month = datetime(2026, 7, 31, 23, 0, tzinfo=timezone.utc)
    for _ in range(settings.free_quota_per_month):
        rec = BodyAssessment(
            user_id=user_id, media_path="uploads/old.jpg", media_type="image"
        )
        rec.created_at = last_month
        db_session.add(rec)
    db_session.commit()

    # 本月共享池计数应为 0（跨月重置）
    assert membership_service.quota_used(db_session, user_id, now=now) == 0
    status = membership_service.check_quota(db_session, user_id, "assess", now=now)
    assert status["used"] == 0
    assert status["remaining"] == settings.free_quota_per_month
    assert status["exhausted"] is False
    # reset_at 为次月 1 日
    assert status["reset_at"] == datetime(2026, 9, 1, tzinfo=timezone.utc)


def test_shared_pool_sums_both_tables(db_session, register_user):
    """共享池 used = 本月 body_assessments + plans 记录数之和。"""
    from app.services import membership_service

    _, user = register_user()
    _seed_assessments(db_session, user["id"], 2)
    _seed_plans(db_session, user["id"], 2)
    assert membership_service.quota_used(db_session, user["id"]) == 4
    st = membership_service.check_quota(db_session, user["id"], "generate_plan")
    assert st["used"] == 4
    assert st["remaining"] == settings.free_quota_per_month - 4
    assert st["exhausted"] is False


def test_quota_month_boundary_wraps_december(db_session, register_user):
    from app.services import membership_service

    _, user = register_user()
    dec = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)
    start, next_start = membership_service.month_bounds(dec)
    assert start == datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert next_start == datetime(2027, 1, 1, tzinfo=timezone.utc)


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
