"""支付回调并发与审计测试——使用真实 SQLite 文件数据库 + 多线程。

与 tests/test_payment.py 的内存库/顺序调用不同，这里：
- 每个用例使用临时**文件** SQLite，开启忙等待；
- 多个线程各自持有独立 DB 连接/会话，通过 Barrier 同时触发同一订单的成功回调，
  真实触发 SQLite 写锁竞争与唯一约束路径（而非顺序调用后宣称并发通过）。

断言口径（WS-34 验收）：
- 同一订单并发回调：仅一次权益变化（expire_at 只加一次 duration）、订单最终 fulfilled、
  无未处理异常；
- 同渠道交易号跨订单竞争：恰好一单核销成功，另一单安全失败（冲突），不重复发货，
  留下 txn_conflict 审计事件；
- 失败后重试：已 failed 的订单不能被迟到的成功回调翻案开通；
- 审计事件覆盖签名失败/金额不一致/币种不一致/重复通知/核销成功/冲突，
  且交易号脱敏、不含签名/密钥/原始回调。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.session import Base
from app.models import Membership, Order, PaymentAuditEvent, User
from app.models.payment_audit import AUDIT_EVENTS
from app.payment import registry
from app.payment.base import PaymentVerifyError
from app.services import payment_service
from app.services.payment_service import PaymentConflictError, PaymentError
from app.core.security import hash_password


# ---------- 夹具：真实文件 SQLite，多连接并发 ----------
@pytest.fixture()
def file_db(tmp_path):
    db_path = tmp_path / "concurrency.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 15},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        # busy_timeout 与 timeout 呼应，减少瞬时 "database is locked"
        cur.execute("PRAGMA busy_timeout=5000")
        # WAL 允许并发读 + 单写，更贴近真实多连接竞争；不改变原子认领的正确性前提
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # 确保 sandbox 渠道启用（默认即 sandbox，这里显式重置注册表缓存）
    registry._enabled.cache_clear()

    seed = Session()
    try:
        yield Session, seed
    finally:
        seed.close()
        engine.dispose()


def _make_user_and_order(seed_session, *, user_id=1, order_no="FF-CONC-1",
                         amount=2800, currency="CNY"):
    user = User(
        id=user_id,
        email=f"u{user_id}@test.com",
        hashed_password=hash_password("secret123"),
        role="user",
        is_active=True,
    )
    seed_session.add(user)
    seed_session.add(
        Membership(user_id=user_id, plan="free", is_active=False)
    )
    order = Order(
        order_no=order_no,
        user_id=user_id,
        plan="pro",
        plan_code="pro_monthly",
        duration_days=30,
        amount_cents=amount,
        currency=currency,
        payment_channel="sandbox",
        status="pending",
    )
    seed_session.add(order)
    seed_session.commit()
    return order


def _sandbox_sign(order_no: str, status: str, amount_cents: int, txn_id: str) -> str:
    msg = f"{order_no}.{status}.{amount_cents}.{txn_id}".encode("utf-8")
    return hmac.new(
        settings.sandbox_secret.encode("utf-8"), msg, hashlib.sha256
    ).hexdigest()


def _callback_payload(order_no: str, txn_id: str, amount: int, currency="CNY",
                      status="success") -> tuple[dict, bytes, dict]:
    body = {
        "order_no": order_no,
        "txn_id": txn_id,
        "status": status,
        "amount_cents": amount,
        "currency": currency,
    }
    sig = _sandbox_sign(order_no, status, amount, txn_id)
    headers = {"x-sandbox-signature": sig}
    return headers, json.dumps(body).encode("utf-8"), body


def _run_concurrent(Session, order_no, txn_id, amount, n_threads, *,
                    currency="CNY", status="success"):
    """在 n_threads 个线程上同时触发同一订单回调，用 Barrier 保证并发起跑。

    返回 (results, exceptions) 列表，顺序与线程一致。
    """
    barrier = threading.Barrier(n_threads)
    results: list = [None] * n_threads
    errors: list = [None] * n_threads

    def _worker(i):
        db = Session()
        try:
            barrier.wait()
            headers, raw, _ = _callback_payload(
                order_no, txn_id, amount, currency=currency, status=status
            )
            order = payment_service.handle_callback(db, "sandbox", headers, raw)
            results[i] = order.status
        except Exception as exc:  # noqa: BLE001  收集起来在主线程断言
            errors[i] = exc
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=n_threads) as pool:
        list(pool.map(_worker, range(n_threads)))
    return results, errors


# ---------- 1. 同一订单并发成功回调：仅一次权益变化 ----------
def test_concurrent_same_order_callbacks_grant_once(file_db):
    Session, seed = file_db
    order = _make_user_and_order(seed, order_no="FF-CONC-SAME")

    n_threads = 16
    results, errors = _run_concurrent(
        Session, order.order_no, "sb_same", order.amount_cents, n_threads
    )

    # 无未处理异常（锁错误应被服务层重试收敛；冲突不应出现在同单并发中）
    unhandled = [e for e in errors if e is not None]
    assert not unhandled, [repr(e) for e in unhandled]

    verify = Session()
    try:
        db_order = verify.scalar(select(Order).where(Order.order_no == order.order_no))
        assert db_order.status == "fulfilled"
        assert db_order.fulfilled_at is not None

        m = verify.scalar(select(Membership).where(Membership.user_id == 1))
        assert m.is_active is True
        assert m.plan == "pro"
        # 时长恰好约 30 天，而不是 30 * 成功线程数
        exp = m.expire_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        delta = exp - datetime.now(timezone.utc)
        assert timedelta(days=29) < delta < timedelta(days=31), delta

        # 审计：恰好一条 fulfilled，其余为 duplicate_notification
        events = verify.scalars(
            select(PaymentAuditEvent).where(
                PaymentAuditEvent.order_no == order.order_no
            )
        ).all()
        fulfilled = [e for e in events if e.event_type == "fulfilled"]
        assert len(fulfilled) == 1, [e.event_type for e in events]
        # 至少有一次重复通知被识别（并发下至少有一个输家）
        dup = [e for e in events if e.event_type == "duplicate_notification"]
        assert len(dup) >= 1
    finally:
        verify.close()


# ---------- 2. 同渠道交易号跨订单/跨用户竞争 ----------
def test_same_txn_id_across_orders_conflicts_and_grants_once(file_db):
    Session, seed = file_db
    order_a = _make_user_and_order(
        seed, user_id=1, order_no="FF-CONF-A", amount=2800
    )
    order_b = _make_user_and_order(
        seed, user_id=2, order_no="FF-CONF-B", amount=2800
    )

    shared_txn = "SHARED-TXN-0001"
    barrier = threading.Barrier(2)
    outcomes = {}

    def _worker(which, order_no):
        db = Session()
        try:
            barrier.wait()
            headers, raw, _ = _callback_payload(order_no, shared_txn, 2800)
            try:
                payment_service.handle_callback(db, "sandbox", headers, raw)
                outcomes[which] = "fulfilled"
            except PaymentConflictError:
                outcomes[which] = "conflict"
            except PaymentError as exc:
                outcomes[which] = f"error:{exc}"
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(_worker, ("A", "B"), (order_a.order_no, order_b.order_no)))

    # 恰好一单成功，另一单冲突
    assert sorted(outcomes.values()) == ["conflict", "fulfilled"], outcomes

    verify = Session()
    try:
        orders = verify.scalars(
            select(Order).where(Order.order_no.in_(["FF-CONF-A", "FF-CONF-B"]))
        ).all()
        statuses = sorted(o.status for o in orders)
        assert statuses == ["fulfilled", "pending"], statuses

        # 只有一个用户被开通 pro
        pros = verify.scalars(
            select(Membership).where(Membership.is_active.is_(True))
        ).all()
        assert len(pros) == 1
        # 共享交易号只绑定到其中一笔订单（唯一约束保证）
        bound = verify.scalars(
            select(Order).where(Order.provider_txn_id == shared_txn)
        ).all()
        assert len(bound) == 1

        # 留下 txn_conflict 审计事件，且包含两笔订单号便于对账
        conflicts = verify.scalars(
            select(PaymentAuditEvent).where(
                PaymentAuditEvent.event_type == "txn_conflict"
            )
        ).all()
        assert len(conflicts) >= 1
        detail = conflicts[0].detail or {}
        assert {"existing_order_no", "incoming_order_no"} <= set(detail)
        # 审计不得包含签名/密钥/原始回调
        assert "signature" not in json.dumps(detail).lower()
    finally:
        verify.close()


# ---------- 3. 连续合法购买顺延（非并发，覆盖顺延路径不回归）----------
def test_consecutive_legit_purchases_extend(file_db):
    Session, seed = file_db
    order1 = _make_user_and_order(seed, order_no="FF-EXT-1")
    headers, raw, _ = _callback_payload(order1.order_no, "sb_ext_1", 2800)
    db = Session()
    payment_service.handle_callback(db, "sandbox", headers, raw)
    db.close()

    order2 = Order(
        order_no="FF-EXT-2", user_id=1, plan="pro", plan_code="pro_monthly",
        duration_days=30, amount_cents=2800, currency="CNY",
        payment_channel="sandbox", status="pending",
    )
    s = Session()
    s.add(order2)
    s.commit()
    s.close()

    headers, raw, _ = _callback_payload("FF-EXT-2", "sb_ext_2", 2800)
    db = Session()
    payment_service.handle_callback(db, "sandbox", headers, raw)
    db.close()

    verify = Session()
    try:
        m = verify.scalar(select(Membership).where(Membership.user_id == 1))
        exp = m.expire_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        delta = exp - datetime.now(timezone.utc)
        assert timedelta(days=59) < delta < timedelta(days=61), delta
    finally:
        verify.close()


# ---------- 4. 失败后重试：failed 订单不能被迟到成功回调翻案 ----------
def test_failed_then_success_does_not_reactivate(file_db):
    Session, seed = file_db
    order = _make_user_and_order(seed, order_no="FF-FAIL-1")

    # 渠道先通知失败
    db = Session()
    headers, raw, _ = _callback_payload(
        order.order_no, "sb_fail_1", 2800, status="failed"
    )
    payment_service.handle_callback(db, "sandbox", headers, raw)
    db.close()

    # 迟到的成功回调（同一笔订单）：不得翻案开通
    db = Session()
    headers, raw, _ = _callback_payload(
        order.order_no, "sb_fail_1", 2800, status="success"
    )
    returned = payment_service.handle_callback(db, "sandbox", headers, raw)
    db.close()

    verify = Session()
    try:
        db_order = verify.scalar(select(Order).where(Order.order_no == order.order_no))
        assert db_order.status == "failed"
        m = verify.scalar(select(Membership).where(Membership.user_id == 1))
        assert not m.is_active
    finally:
        verify.close()


# ---------- 5. 审计事件覆盖与脱敏 ----------
def test_audit_events_recorded_and_sanitized(file_db):
    Session, seed = file_db
    order = _make_user_and_order(seed, order_no="FF-AUD-1")

    # 5a 伪造签名 -> signature_failed
    db = Session()
    try:
        with pytest.raises(PaymentVerifyError):
            payment_service.handle_callback(
                db, "sandbox",
                {"x-sandbox-signature": "badsig"},
                json.dumps({"order_no": order.order_no, "txn_id": "sb_aud_1",
                            "status": "success", "amount_cents": 2800}).encode(),
            )
    finally:
        db.close()

    # 5b 金额不一致 -> amount_mismatch（签名对应该篡改体，验签通过但服务端拒绝）
    db = Session()
    try:
        headers, raw, _ = _callback_payload(order.order_no, "sb_aud_1", 1)
        with pytest.raises(PaymentError):
            payment_service.handle_callback(db, "sandbox", headers, raw)
    finally:
        db.close()

    # 5c 币种不一致 -> currency_mismatch
    #    沙箱签名不覆盖 currency，构造一个金额正确但币种被改为 USD 的回调
    db = Session()
    try:
        headers, raw, _ = _callback_payload(
            order.order_no, "sb_aud_1", 2800, currency="USD"
        )
        with pytest.raises(PaymentError):
            payment_service.handle_callback(db, "sandbox", headers, raw)
    finally:
        db.close()

    # 5d 正常核销 -> fulfilled；再重放一次 -> duplicate_notification
    db = Session()
    headers, raw, _ = _callback_payload(order.order_no, "sb_aud_1", 2800)
    payment_service.handle_callback(db, "sandbox", headers, raw)
    payment_service.handle_callback(db, "sandbox", headers, raw)
    db.close()

    verify = Session()
    try:
        events = verify.scalars(select(PaymentAuditEvent)).all()
        types = {e.event_type for e in events}
        assert "signature_failed" in types
        assert "amount_mismatch" in types
        assert "currency_mismatch" in types
        assert "fulfilled" in types
        assert "duplicate_notification" in types

        # 所有 event_type 必须在模型白名单内
        assert all(e.event_type in AUDIT_EVENTS for e in events)

        # 脱敏：交易号提示只保留首尾，不出现完整 txn_id / 签名 / secret
        for e in events:
            blob = json.dumps(
                {"hint": e.provider_txn_hint, "detail": e.detail}, default=str
            )
            assert "sb_aud_1" not in blob  # 完整交易号不得出现在审计
            assert "badsig" not in blob
            assert settings.sandbox_secret not in blob
    finally:
        verify.close()
