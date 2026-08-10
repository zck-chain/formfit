"""支付链路测试：下单→沙箱回调→会员开通，以及验签/幂等/恢复购买。"""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models import Membership, Order


def _sandbox_sign(order_no: str, status: str, amount_cents: int, txn_id: str) -> str:
    msg = f"{order_no}.{status}.{amount_cents}.{txn_id}".encode("utf-8")
    return hmac.new(
        settings.sandbox_secret.encode("utf-8"), msg, hashlib.sha256
    ).hexdigest()


def _create_order(client, headers, plan_code="pro_monthly", channel="sandbox"):
    resp = client.post(
        "/api/payment/orders",
        json={"plan_code": plan_code, "channel": channel},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _successful_callback(client, order_data, amount=None):
    sb = order_data["pay_credential"]["sandbox"]
    body = {
        "order_no": order_data["order_no"],
        "txn_id": sb["txn_id"],
        "status": "success",
        "amount_cents": amount if amount is not None else sb["amount_cents"],
        "currency": "CNY",
    }
    sig = _sandbox_sign(body["order_no"], "success", body["amount_cents"], body["txn_id"])
    return client.post(
        f"/api/payment/callback/sandbox",
        json=body,
        headers={"x-sandbox-signature": sig},
    )


# ---------- 套餐与渠道 ----------
def test_list_plans(client):
    resp = client.get("/api/payment/plans?channel=sandbox")
    assert resp.status_code == 200
    plans = resp.json()
    assert any(p["plan_code"] == "pro_monthly" for p in plans)
    assert all(p["amount_cents"] > 0 for p in plans)


def test_unknown_channel_rejected(client, register_user):
    headers, _ = register_user()
    resp = client.post(
        "/api/payment/orders",
        json={"plan_code": "pro_monthly", "channel": "wechat"},
        headers=headers,
    )
    assert resp.status_code == 400


# ---------- 完整链路 ----------
def test_full_sandbox_flow_membership_activated(client, register_user, db_session):
    headers, user = register_user()
    order = _create_order(client, headers)
    assert order["status"] == "pending"
    assert order["amount_cents"] == 2800

    # 支付前会员未开通
    m_before = db_session.get(Membership, 1)  # register 创建 id=1 membership
    assert m_before.plan == "free"
    assert not m_before.is_active

    # 回调
    resp = _successful_callback(client, order)
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == "ok"

    db_session.expire_all()
    m = db_session.query(Membership).filter_by(user_id=user["id"]).one()
    assert m.is_active is True
    assert m.plan == "pro"
    assert m.order_id == order["order_no"]
    assert m.payment_channel == "sandbox"
    assert m.expire_at is not None
    # 约 30 天
    exp = m.expire_at.replace(tzinfo=timezone.utc) if m.expire_at.tzinfo is None else m.expire_at
    assert timedelta(days=29) < exp - datetime.now(timezone.utc) < timedelta(days=31)

    # 订单终态
    db_order = db_session.query(Order).filter_by(order_no=order["order_no"]).one()
    assert db_order.status == "fulfilled"
    assert db_order.fulfilled_at is not None


def test_order_status_reflects_membership(client, register_user):
    headers, _ = register_user()
    order = _create_order(client, headers)

    resp = client.get(f"/api/payment/orders/{order['order_no']}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["is_active"] is False

    _successful_callback(client, order)

    resp = client.get(f"/api/payment/orders/{order['order_no']}", headers=headers)
    data = resp.json()
    assert data["status"] == "fulfilled"
    assert data["is_active"] is True
    assert data["expire_at"] is not None


# ---------- 安全：伪造回调 ----------
def test_forged_signature_does_not_activate(client, register_user, db_session):
    headers, _ = register_user()
    order = _create_order(client, headers)
    sb = order["pay_credential"]["sandbox"]

    body = {
        "order_no": order["order_no"],
        "txn_id": sb["txn_id"],
        "status": "success",
        "amount_cents": 2800,
    }
    # 错误签名
    resp = client.post(
        "/api/payment/callback/sandbox",
        json=body,
        headers={"x-sandbox-signature": "deadbeef"},
    )
    assert resp.status_code == 401

    db_session.expire_all()
    m = db_session.query(Membership).filter_by(user_id=1).one()
    assert not m.is_active
    db_order = db_session.query(Order).filter_by(order_no=order["order_no"]).one()
    assert db_order.status == "pending"


def test_tampered_amount_rejected_server_side(client, register_user, db_session):
    """回调金额与订单金额不一致时，即使签名对应该回调体，也必须拒绝开通。"""
    headers, _ = register_user()
    order = _create_order(client, headers)
    sb = order["pay_credential"]["sandbox"]
    body = {
        "order_no": order["order_no"],
        "txn_id": sb["txn_id"],
        "status": "success",
        "amount_cents": 1,  # 篡改为 1 分
        "currency": "CNY",
    }
    # 签名对应该（已篡改的）回调体——验签通过，但金额与订单不符
    sig = _sandbox_sign(body["order_no"], "success", body["amount_cents"], body["txn_id"])
    resp = client.post(
        "/api/payment/callback/sandbox",
        json=body,
        headers={"x-sandbox-signature": sig},
    )
    # 金额不一致 -> 拒绝（验签通过但内容与订单不符 -> 400）
    assert resp.status_code == 400, resp.text

    db_session.expire_all()
    m = db_session.query(Membership).filter_by(user_id=1).one()
    assert not m.is_active
    db_order = db_session.query(Order).filter_by(order_no=order["order_no"]).one()
    assert db_order.status == "pending"


# ---------- 幂等：重放回调 ----------
def test_replay_callback_is_idempotent(client, register_user, db_session):
    headers, _ = register_user()
    order = _create_order(client, headers)
    _successful_callback(client, order)

    db_session.expire_all()
    m = db_session.query(Membership).filter_by(user_id=1).one()
    first_expire = m.expire_at

    # 重放同一回调
    resp = _successful_callback(client, order)
    assert resp.status_code == 200

    db_session.expire_all()
    m = db_session.query(Membership).filter_by(user_id=1).one()
    # 时长不能叠加
    assert m.expire_at == first_expire
    db_order = db_session.query(Order).filter_by(order_no=order["order_no"]).one()
    assert db_order.status == "fulfilled"


def test_consecutive_purchases_extend_membership(client, register_user, db_session):
    """连续购买两单应顺延（不是覆盖）。"""
    headers, _ = register_user()
    o1 = _create_order(client, headers)
    _successful_callback(client, o1)

    o2 = _create_order(client, headers)
    _successful_callback(client, o2)

    db_session.expire_all()
    m = db_session.query(Membership).filter_by(user_id=1).one()
    exp = m.expire_at.replace(tzinfo=timezone.utc) if m.expire_at.tzinfo is None else m.expire_at
    # 约 60 天
    assert timedelta(days=59) < exp - datetime.now(timezone.utc) < timedelta(days=61)


def test_callback_for_nonexistent_order_returns_4xx(client):
    body = {"order_no": "FFNOPE", "txn_id": "sb_FFNOPE", "status": "success", "amount_cents": 100}
    sig = _sandbox_sign("FFNOPE", "success", 100, "sb_FFNOPE")
    resp = client.post(
        "/api/payment/callback/sandbox",
        json=body,
        headers={"x-sandbox-signature": sig},
    )
    assert resp.status_code == 400


def test_other_user_order_not_visible(client, register_user):
    h1, _ = register_user("a@test.com")
    h2, _ = register_user("b@test.com", password="secret123")
    order = _create_order(client, h1)
    resp = client.get(f"/api/payment/orders/{order['order_no']}", headers=h2)
    assert resp.status_code == 404


# ---------- 恢复购买（沙箱票据）----------
def test_restore_purchase_sandbox(client, register_user, db_session):
    headers, user = register_user()
    # 沙箱票据 txn_id:product_id:sign
    txn_id = "sb_restore_1"
    product_id = "formfit.pro.monthly"  # 注意：sandbox 渠道的 product 映射走 provider_product_id.sandbox
    # 为 sandbox 渠道临时配置商品映射
    from app.schemas.payment import PLAN_CATALOG

    PLAN_CATALOG["pro_monthly"]["provider_product_id"]["sandbox"] = product_id
    try:
        msg = f"{txn_id}.{product_id}".encode("utf-8")
        sig = hmac.new(
            settings.sandbox_secret.encode("utf-8"), msg, hashlib.sha256
        ).hexdigest()
        receipt = f"{txn_id}:{product_id}:{sig}"

        resp = client.post(
            "/api/payment/restore",
            json={"channel": "sandbox", "receipt_data": receipt},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "fulfilled"

        # 重复恢复应幂等（同一 original txn）
        resp2 = client.post(
            "/api/payment/restore",
            json={"channel": "sandbox", "receipt_data": receipt},
            headers=headers,
        )
        assert resp2.status_code == 200

        db_session.expire_all()
        m = db_session.query(Membership).filter_by(user_id=user["id"]).one()
        assert m.is_active is True
        assert m.provider_subscription_id == txn_id
    finally:
        PLAN_CATALOG["pro_monthly"]["provider_product_id"].pop("sandbox", None)


def test_restore_forged_receipt_rejected(client, register_user, db_session):
    headers, _ = register_user()
    resp = client.post(
        "/api/payment/restore",
        json={"channel": "sandbox", "receipt_data": "x:y:badsig"},
        headers=headers,
    )
    assert resp.status_code == 401
    db_session.expire_all()
    m = db_session.query(Membership).filter_by(user_id=1).one()
    assert not m.is_active


# ---------- 核销幂等：服务层重复处理同一回调 ----------
def test_fulfill_order_is_idempotent_on_repeat(client, register_user, db_session):
    """同一 PaymentResult 连续核销两次：只开通一次，fulfilled_at/expire_at 不变。"""
    from app.payment import get_provider
    from app.services import payment_service

    headers, _ = register_user()
    order = _create_order(client, headers)
    sb = order["pay_credential"]["sandbox"]
    body = {
        "order_no": order["order_no"],
        "txn_id": sb["txn_id"],
        "status": "success",
        "amount_cents": sb["amount_cents"],
        "currency": "CNY",
    }
    sig = _sandbox_sign(body["order_no"], "success", body["amount_cents"], body["txn_id"])
    result = get_provider("sandbox").verify_callback(
        {"x-sandbox-signature": sig},
        json.dumps(body).encode("utf-8"),
    )

    db_order = db_session.query(Order).filter_by(order_no=order["order_no"]).one()
    first = payment_service.fulfill_order(db_session, db_order, result)
    db_session.commit()
    assert first is True

    m1 = db_session.query(Membership).filter_by(user_id=1).one()
    expire1, fulfilled1 = m1.expire_at, db_order.fulfilled_at
    assert db_order.status == "fulfilled"

    # 重复核销：返回 False 表示幂等跳过
    second = payment_service.fulfill_order(db_session, db_order, result)
    db_session.commit()
    assert second is False

    db_session.expire_all()
    m2 = db_session.query(Membership).filter_by(user_id=1).one()
    db_order2 = db_session.query(Order).filter_by(order_no=order["order_no"]).one()
    # 时长不叠加、核销时间不变
    assert m2.expire_at == expire1
    assert db_order2.fulfilled_at == fulfilled1
    assert db_order2.status == "fulfilled"
