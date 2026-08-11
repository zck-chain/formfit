"""端到端集成测试：注册→档案→体态评估（mock Qwen-VL）→生成计划（DeepSeek 保底路径）
→计划详情→训练日志写入；free 用户通过真实 API 耗尽共享池；沙箱支付后门控放行；
普通用户越权访问 /admin 被拒。

与单元测试的区别：不在 DB 里直接 seed 已用次数，而是通过真实 HTTP 调用让
记录自然落库，验证整条闭环的串联与计数口径一致。
"""
import io

import pytest
from PIL import Image

from app.models import Exercise


# ---------- 夹具：1x1 PNG / 动作种子 ----------
def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _seed_exercises(db_session):
    """为保底计划的 6 个部位各塞一条自重动作，使 fallback 能产出真实 items。"""
    cats = [
        ("chest", "pectorals"),
        ("back", "lats"),
        ("upper legs", "quads"),
        ("shoulders", "delts"),
        ("waist", "abs"),
        ("upper arms", "biceps"),
    ]
    for i, (cat, target) in enumerate(cats, start=1):
        ex_id = f"E2E{i:04d}"
        db_session.add(
            Exercise(
                id=ex_id,
                name=f"Exercise {cat}",
                category=cat,
                equipment="body weight",
                target=target,
                secondary_muscles=[],
                instructions={"zh": "步骤一。步骤二。"},
                instruction_steps={"zh": ["步骤一", "步骤二"]},
                image=f"images/{ex_id}.jpg",
                gif_url=f"images/{ex_id}.gif",
            )
        )
    db_session.commit()


@pytest.fixture()
def _force_fallback_plan(monkeypatch):
    """把 DeepSeek chat 钉成"无工具调用 + 非 JSON 内容"，强制 planner 走 _fallback_plan。"""

    async def _fake_chat(messages, tools=None, temperature=0.7, timeout=60.0):
        return {"role": "assistant", "content": "模型暂不可用", "tool_calls": None}

    monkeypatch.setattr("app.agent.deepseek_client.chat", _fake_chat)


@pytest.fixture()
def _silent_upload(monkeypatch, tmp_path):
    """评估上传不真实落盘，写入临时目录。"""
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "upload_dir", tmp_path)


@pytest.fixture()
def _mock_qwen(monkeypatch):
    async def _fake_assess(path, **kwargs):
        return {
            "direction": "gain",
            "body_type": "ectomorph",
            "summary": "E2E 评估",
            "observed": ["肩部紧张"],
            "safety_notes": None,
        }

    monkeypatch.setattr("app.agent.qwen_vl_client.assess_body", _fake_assess)


# ============================================================
# 1. 完整用户闭环（free 用户，额度内）
# ============================================================
def test_full_user_journey_register_profile_assess_plan_log(
    client, register_user, db_session, _force_fallback_plan, _silent_upload, _mock_qwen
):
    _seed_exercises(db_session)
    headers, user = register_user(email="journey@test.com")

    # 1) 填档案
    profile_resp = client.put(
        "/api/fitness/profile",
        headers=headers,
        json={
            "gender": "male",
            "age": 28,
            "height_cm": 178,
            "weight_kg": 72,
            "goal": "增肌",
            "level": "beginner",
            "days_per_week": 3,
            "available_equipment": ["body weight"],
        },
    )
    assert profile_resp.status_code == 200, profile_resp.text
    assert profile_resp.json()["goal"] == "增肌"

    # GET 档案应已持久化
    got = client.get("/api/fitness/profile", headers=headers)
    assert got.status_code == 200
    assert got.json()["days_per_week"] == 3

    # 2) 体态评估（mock Qwen-VL）
    assess_resp = client.post(
        "/api/fitness/assess",
        headers=headers,
        files={"file": ("a.png", _png_bytes(), "image/png")},
        data={"height_cm": "178", "weight_kg": "72"},
    )
    assert assess_resp.status_code == 200, assess_resp.text
    assessment = assess_resp.json()
    assert assessment["direction"] == "gain"
    assert assessment["id"] is not None
    # 门控头：首次 assess 前满额 5
    assert assess_resp.headers["X-Quota-Remaining"] == "5"

    # 3) 生成计划（保底路径）
    plan_resp = client.post(
        "/api/fitness/plans/generate",
        headers=headers,
        json={"goal": "增肌", "assessment_id": assessment["id"]},
    )
    assert plan_resp.status_code == 200, plan_resp.text
    plan = plan_resp.json()
    assert plan["title"]  # 保底计划非空标题
    # 保底计划应包含真实动作（来自 seed），且每个 item 带中文/媒体字段
    days = plan["content"].get("days", [])
    assert days, "保底计划应至少有一个训练日"
    all_items = [it for d in days for it in d.get("items", [])]
    assert all_items, "保底计划应至少包含一个动作"
    first_item = all_items[0]
    assert first_item["exercise_id"].startswith("E2E")
    assert "steps_zh" in first_item and "gif_url" in first_item
    plan_id = plan["id"]

    # 4) 计划详情 / 列表
    detail = client.get(f"/api/fitness/plans/{plan_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == plan_id

    plan_list = client.get("/api/fitness/plans", headers=headers)
    assert plan_list.status_code == 200
    assert any(p["id"] == plan_id for p in plan_list.json())

    # 5) 写训练日志（引用计划中真实动作 id）
    ex_id = all_items[0]["exercise_id"]
    log_resp = client.post(
        "/api/fitness/logs",
        headers=headers,
        json={
            "plan_id": plan_id,
            "title": "第一次训练",
            "duration_min": 45,
            "note": "状态不错",
            "sets": [
                {"exercise_id": ex_id, "set_index": 0, "reps": 10, "weight_kg": 0, "done": True},
                {"exercise_id": ex_id, "set_index": 1, "reps": 10, "weight_kg": 0, "done": True},
            ],
        },
    )
    assert log_resp.status_code == 200, log_resp.text
    log_data = log_resp.json()
    assert log_data["title"] == "第一次训练"
    assert len(log_data["sets"]) == 2
    assert log_data["sets"][0]["exercise_id"] == ex_id

    logs = client.get("/api/fitness/logs", headers=headers)
    assert logs.status_code == 200
    assert len(logs.json()) == 1

    # 6) 会员态：共享池已用 = 1 assess + 1 plan = 2
    mem = client.get("/api/membership", headers=headers).json()
    assert mem["plan"] == "free"
    assert mem["quota"]["used"] == 2
    assert mem["quota"]["remaining"] == 3
    assert mem["quota"]["breakdown"] == {"assess": 1, "generate_plan": 1}


# ============================================================
# 2. free 用户通过真实 API 耗尽共享池，第 6 次 402（混用）
# ============================================================
def test_free_user_exhausts_shared_pool_via_real_calls(
    client, register_user, db_session, _force_fallback_plan, _silent_upload, _mock_qwen
):
    _seed_exercises(db_session)
    headers, _ = register_user(email="pool@test.com")

    def assess():
        return client.post(
            "/api/fitness/assess",
            headers=headers,
            files={"file": ("a.png", _png_bytes(), "image/png")},
        )

    def generate():
        return client.post(
            "/api/fitness/plans/generate", headers=headers, json={"goal": "减脂"}
        )

    # 3 assess + 2 plan = 5（全部 200）
    for i in range(3):
        r = assess()
        assert r.status_code == 200, (i, r.text)
    for i in range(2):
        r = generate()
        assert r.status_code == 200, (i, r.text)

    mem = client.get("/api/membership", headers=headers).json()
    assert mem["quota"]["used"] == 5
    assert mem["quota"]["remaining"] == 0

    # 第 6 次 assess 被 402
    r6 = assess()
    assert r6.status_code == 402, r6.text
    body = r6.json()["detail"]
    assert body["error"] == "quota_exhausted"
    assert body["feature"] == "assess"
    assert body["used"] == 5
    assert body["limit"] == 5

    # 第 6 次换成 plan 同样 402（共享池）
    r6b = generate()
    assert r6b.status_code == 402
    assert r6b.json()["detail"]["feature"] == "generate_plan"

    # 被拒后池计数不增加（不会因为 402 再 +1 滚雪球）
    mem_after = client.get("/api/membership", headers=headers).json()
    assert mem_after["quota"]["used"] == 5


# ============================================================
# 3. 额度用尽 → 沙箱支付 → 会员开通 → 门控放行（端到端串联）
# ============================================================
def _sandbox_sign(settings, order_no, status, amount, txn_id):
    import hashlib
    import hmac

    msg = f"{order_no}.{status}.{amount}.{txn_id}".encode()
    return hmac.new(settings.sandbox_secret.encode(), msg, hashlib.sha256).hexdigest()


def test_quota_exhausted_then_sandbox_payment_unblocks(
    client, register_user, db_session, _force_fallback_plan, _silent_upload, _mock_qwen
):
    from app.core.config import settings

    _seed_exercises(db_session)
    headers, user = register_user(email="payunblock@test.com")

    # 直接用满 5 次 plan（避免反复上传文件）
    for _ in range(5):
        r = client.post(
            "/api/fitness/plans/generate", headers=headers, json={"goal": "增肌"}
        )
        assert r.status_code == 200, r.text
    assert client.post(
        "/api/fitness/plans/generate", headers=headers, json={"goal": "增肌"}
    ).status_code == 402

    # 沙箱下单
    order = client.post(
        "/api/payment/orders",
        headers=headers,
        json={"plan_code": "pro_monthly", "channel": "sandbox"},
    )
    assert order.status_code == 200, order.text
    order_data = order.json()
    sb = order_data["pay_credential"]["sandbox"]

    # 渠道回调
    body = {
        "order_no": order_data["order_no"],
        "txn_id": sb["txn_id"],
        "status": "success",
        "amount_cents": sb["amount_cents"],
        "currency": "CNY",
    }
    sig = _sandbox_sign(
        settings, body["order_no"], "success", body["amount_cents"], body["txn_id"]
    )
    cb = client.post(
        "/api/payment/callback/sandbox",
        json=body,
        headers={"x-sandbox-signature": sig},
    )
    assert cb.status_code == 200, cb.text

    # 会员态刷新为 pro
    mem = client.get("/api/membership", headers=headers).json()
    assert mem["is_pro"] is True
    assert mem["features_locked"] is False
    assert mem["quota"]["remaining"] is None  # 不限次

    # 门控放行：再次生成计划 200，且不再返回 X-Quota-Remaining 数值
    r = client.post(
        "/api/fitness/plans/generate", headers=headers, json={"goal": "增肌"}
    )
    assert r.status_code == 200, r.text
    assert "x-quota-remaining" not in {k.lower() for k in r.headers.keys()}


# ============================================================
# 4. 后台越权：普通用户（持有效 JWT）不能访问 /admin
# ============================================================
def test_regular_user_cannot_access_admin(client, register_user):
    headers, _ = register_user(email="normal@test.com")
    # 带 Bearer JWT 访问后台各页面：admin 鉴权走独立 session cookie，
    # 不接受 API JWT，应全部 303 跳登录（不是 200，也不是 500）
    for path in ("/admin", "/admin/users", "/admin/membership", "/admin/exercises"):
        r = client.get(path, headers=headers, follow_redirects=False)
        assert r.status_code == 303, (path, r.status_code)
        assert r.headers.get("location", "").endswith("/admin/login")

    # 写操作同样被拦（不允许普通用户通过 POST 改数据）
    r = client.post("/admin/membership/1", headers=headers, data={"plan": "pro", "days": 30},
                    follow_redirects=False)
    assert r.status_code == 303
    # 并且会员没被改动
    mem = client.get("/api/membership", headers=headers).json()
    assert mem["is_pro"] is False


def test_anonymous_cannot_access_admin(client):
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location", "").endswith("/admin/login")


# ============================================================
# 5. 跨用户隔离：A 看不到 B 的计划详情（404，不泄漏存在性）
# ============================================================
def test_cross_user_plan_detail_is_404(
    client, register_user, db_session, _force_fallback_plan
):
    _seed_exercises(db_session)
    h_a, _ = register_user("a@test.com")
    h_b, _ = register_user("b@test.com", password="secret123")

    plan = client.post(
        "/api/fitness/plans/generate", headers=h_a, json={"goal": "增肌"}
    )
    assert plan.status_code == 200
    plan_id = plan.json()["id"]

    # B 拿 A 的 plan_id 查详情 → 404
    r = client.get(f"/api/fitness/plans/{plan_id}", headers=h_b)
    assert r.status_code == 404
