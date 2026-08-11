"""支付业务服务：下单、回调核销、会员开通/续期、恢复购买。

核销幂等与并发正确性有四道闸门：

1. ``(payment_channel, provider_txn_id)`` 唯一约束——同渠道同交易号只能落一笔订单，
   跨订单复用同一交易号在 flush/commit 时触发 ``IntegrityError``，被识别为冲突并安全失败；
2. 数据库层原子"认领"（compare-and-set）：
   ``UPDATE orders SET ... WHERE id=:id AND fulfilled_at IS NULL``，
   以 rowcount 判断是否本请求抢到核销权。SQLite 写事务串行 + 该条件更新，
   保证同一笔订单无论多少并发回调都只有一次真正开通，不依赖 Python 层读判断，
   也不依赖 ``SELECT ... FOR UPDATE``（SQLite 不支持，伪造也无效）；
3. ``Order.fulfilled_at`` 终态——重复回调直接幂等返回，不重复加时长；
4. 会员时长在同一事务内计算并提交，认领失败即回滚，权益不会叠加。

SQLite 不支持行锁，生产为单 worker；并发下可能抛 ``database is locked``，
本模块在回调入口做有限次退避重试（仅重试可安全重试的锁错误），重试后重新读单，
因此即使抢锁失败也不会重复发货。
"""
from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models import Membership, Order, User
from app.payment import PaymentResult, get_provider, provider_exists
from app.payment.audit import (
    EVT_AMOUNT_MISMATCH,
    EVT_CURRENCY_MISMATCH,
    EVT_DUPLICATE_NOTIFICATION,
    EVT_FAILED,
    EVT_FULFILLED,
    EVT_ORDER_NOT_FOUND,
    EVT_SIGNATURE_FAILED,
    EVT_TXN_CONFLICT,
    record_audit,
)
from app.payment.base import PaymentVerifyError
from app.schemas.payment import PLAN_CATALOG

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    """业务层支付错误（参数/状态不合法），由路由转成 4xx。"""


class PaymentConflictError(PaymentError):
    """同一渠道交易号已核销到另一笔订单/用户——安全失败，必须留对账事件。

    路由映射为 409；这不是渠道重试可解决的问题，需人工对账。
    """


# SQLite "database is locked" 的有限重试参数。生产单 worker 下写事务串行，
# 仅在 FastAPI 线程池并发回调同一文件库时短暂抢锁，5 次指数退避足够收敛。
_LOCK_RETRY_MAX = 5
_LOCK_RETRY_BASE_SLEEP = 0.02  # 秒，按尝试次数线性退避


# 方言能力缓存：SQLite 不支持 SELECT ... FOR UPDATE（其写事务本身串行）
_ROW_LOCK_UNKNOWN = object()
_row_lock_supported: object = _ROW_LOCK_UNKNOWN


def _supports_row_lock(db: Session) -> bool:
    global _row_lock_supported
    if _row_lock_supported is _ROW_LOCK_UNKNOWN:
        bind = db.bind
        _row_lock_supported = bool(bind and bind.dialect.name != "sqlite")
    return bool(_row_lock_supported)


def _for_update(db: Session, stmt):
    """Postgres/MySQL 下加行锁 ``FOR UPDATE`` 串行化同订单并发回调；
    SQLite 直接降级（其写事务本身串行，且本模块以原子认领为并发正确性来源）。"""
    if _supports_row_lock(db):
        return stmt.with_for_update()
    return stmt


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _gen_order_no() -> str:
    # 时间序 + 随机熵，足够短且不可猜；不暴露自增 id
    return _now().strftime("FF%Y%m%d%H%M%S") + secrets.token_hex(4)


def _catalog(plan_code: str) -> dict:
    item = PLAN_CATALOG.get(plan_code)
    if not item:
        raise PaymentError(f"未知套餐：{plan_code}")
    return item


def _get_membership(db: Session, user_id: int) -> Membership:
    m = db.scalar(select(Membership).where(Membership.user_id == user_id))
    if not m:
        # 注册流程已为每个用户建会员行，这里仅兜底。用 savepoint 包裹插入：
        # 并发下若两个事务都为同一 user 建行，一个提交成功，另一个在此命中
        # user_id 唯一约束——只回滚该 savepoint，绝不能回滚外层核销事务。
        m = Membership(user_id=user_id, plan="free", is_active=False)
        db.add(m)
        try:
            with db.begin_nested():
                db.flush()
        except IntegrityError:
            db.rollback()
            m = db.scalar(select(Membership).where(Membership.user_id == user_id))
            if not m:
                raise
    return m


def create_order(db: Session, user: User, plan_code: str, channel: str) -> Order:
    """创建订单并调用渠道预下单。金额以服务端目录为准，不信客户端。"""
    if not provider_exists(channel):
        raise PaymentError(f"支付渠道未启用：{channel}")
    item = _catalog(plan_code)

    order = Order(
        order_no=_gen_order_no(),
        user_id=user.id,
        plan=item["plan"],
        plan_code=plan_code,
        duration_days=int(item["duration_days"]),
        amount_cents=int(item["amount_cents"]),
        currency=item.get("currency", "CNY"),
        payment_channel=channel,
        status="pending",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def build_pay_credential(order: Order) -> dict:
    """调用渠道生成客户端支付凭据（独立函数，便于下单后再获取/刷新）。"""
    provider = get_provider(order.payment_channel)
    return provider.create_payment(order)


def _apply_membership(
    db: Session,
    user_id: int,
    plan: str,
    duration_days: int,
    channel: str,
    order_no: str,
    provider_subscription_id: str | None = None,
) -> Membership:
    """开通或续期会员。若当前未过期则在到期时间上顺延，否则从现在起算。"""
    m = _get_membership(db, user_id)
    now = _now()
    current_expire = m.expire_at
    if current_expire is not None and current_expire.tzinfo is None:
        current_expire = current_expire.replace(tzinfo=timezone.utc)
    base = current_expire if (m.is_active and current_expire and current_expire > now) else now

    m.plan = plan
    m.is_active = True
    m.start_at = m.start_at or now
    m.expire_at = base + timedelta(days=duration_days)
    m.order_id = order_no
    m.payment_channel = channel
    if provider_subscription_id:
        m.provider_subscription_id = provider_subscription_id
    return m


def _verify_amount_and_currency(order: Order, result: PaymentResult) -> None:
    """金额以服务端订单为准；渠道回传金额/币种与订单不一致一律拒绝（防短款/篡改）。"""
    if result.amount_cents is not None and int(result.amount_cents) != order.amount_cents:
        raise PaymentError(
            f"回调金额 {result.amount_cents} 与订单金额 {order.amount_cents} 不一致"
        )
    if result.currency and order.currency:
        if str(result.currency).strip().upper() != str(order.currency).strip().upper():
            raise PaymentError(
                f"回调币种 {result.currency} 与订单币种 {order.currency} 不一致"
            )


def fulfill_order(db: Session, order: Order, result: PaymentResult) -> bool:
    """在事务内把订单标记成功并核销。

    返回 True 表示本次真的开通；False 表示重复回调幂等跳过。
    任何金额/币种/交易号冲突都先记录审计事件再抛错。
    """
    # 终态快速路径：已核销（内存或 DB 状态）直接幂等返回。
    # 并发正确性不依赖此判断——原子认领 UPDATE 才是权威闸门。
    if order.fulfilled_at is not None or order.status == "fulfilled":
        record_audit(
            db,
            channel=order.payment_channel,
            event_type=EVT_DUPLICATE_NOTIFICATION,
            result="ignored",
            order_no=order.order_no,
            provider_txn_id=result.provider_txn_id,
            user_id=order.user_id,
        )
        return False

    if result.success and order.status not in ("paid", "pending"):
        # 已 failed/refunded 的订单不允许被成功回调翻案
        return False

    if not result.success:
        # 渠道明确通知失败：仅当仍在 pending/paid 时标记 failed，终态不改写
        if order.status in ("pending", "paid"):
            order.status = "failed"
            order.raw_callback = _safe_raw(result)
            db.commit()
        record_audit(
            db,
            channel=order.payment_channel,
            event_type=EVT_FAILED,
            result="success",
            order_no=order.order_no,
            provider_txn_id=result.provider_txn_id,
            user_id=order.user_id,
        )
        return False

    # 成功路径：先校验金额/币种（此时无任何待提交写，审计可独立提交后抛错）
    try:
        _verify_amount_and_currency(order, result)
    except PaymentError as exc:
        event = (
            EVT_AMOUNT_MISMATCH if "金额" in str(exc) else EVT_CURRENCY_MISMATCH
        )
        record_audit(
            db,
            channel=order.payment_channel,
            event_type=event,
            result="rejected",
            order_no=order.order_no,
            provider_txn_id=result.provider_txn_id,
            user_id=order.user_id,
            detail={
                "expected_cents": order.amount_cents,
                "actual_cents": result.amount_cents,
                "expected_currency": order.currency,
                "actual_currency": result.currency,
            },
        )
        raise

    return _claim_and_fulfill(db, order, result)


def _claim_and_fulfill(db: Session, order: Order, result: PaymentResult) -> bool:
    """绑定交易号 → 原子认领订单 → 开通会员，全部在一个事务内。"""
    now = _now()
    try:
        # 1) 绑定渠道交易号。若另一笔订单已占用同 (channel, txn_id)，
        #    flush 立即抛 IntegrityError（比等到 commit 更早、更明确）。
        if result.provider_txn_id and not order.provider_txn_id:
            order.provider_txn_id = result.provider_txn_id
            db.flush()

        order.paid_at = order.paid_at or now
        order.raw_callback = _safe_raw(result)

        # 2) 原子认领：只有 fulfilled_at 仍为 NULL 的订单能被更新为 fulfilled。
        #    rowcount=0 说明并发下已有另一个回调抢先核销——本次幂等跳过。
        claimed = db.execute(
            update(Order)
            .where(Order.id == order.id, Order.fulfilled_at.is_(None))
            .values(status="fulfilled", fulfilled_at=now)
        ).rowcount

        if claimed == 0:
            db.rollback()
            record_audit(
                db,
                channel=order.payment_channel,
                event_type=EVT_DUPLICATE_NOTIFICATION,
                result="ignored",
                order_no=order.order_no,
                provider_txn_id=result.provider_txn_id,
                user_id=order.user_id,
            )
            return False

        # 3) 认领成功后开通/顺延会员（与订单认领同事务，任一失败整体回滚）。
        _apply_membership(
            db,
            user_id=order.user_id,
            plan=order.plan,
            duration_days=order.duration_days,
            channel=order.payment_channel,
            order_no=order.order_no,
            provider_subscription_id=result.original_transaction_id,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        return _handle_claim_integrity_error(db, order, result, exc)
    except OperationalError:
        db.rollback()
        raise

    record_audit(
        db,
        channel=order.payment_channel,
        event_type=EVT_FULFILLED,
        result="success",
        order_no=order.order_no,
        provider_txn_id=result.provider_txn_id,
        user_id=order.user_id,
        detail={
            "plan": order.plan,
            "duration_days": order.duration_days,
            "amount_cents": order.amount_cents,
            "currency": order.currency,
        },
    )
    return True


def _handle_claim_integrity_error(
    db: Session, order: Order, result: PaymentResult, exc: IntegrityError
) -> bool:
    """认领提交时唯一约束冲突：区分跨订单交易号冲突（必须对账）与本单已被并发核销（幂等）。"""
    # 跨订单冲突：另一笔订单已占用该 (channel, provider_txn_id)
    if result.provider_txn_id:
        other = db.scalar(
            select(Order).where(
                Order.payment_channel == order.payment_channel,
                Order.provider_txn_id == result.provider_txn_id,
                Order.id != order.id,
            )
        )
        if other:
            record_audit(
                db,
                channel=order.payment_channel,
                event_type=EVT_TXN_CONFLICT,
                result="rejected",
                order_no=order.order_no,
                provider_txn_id=result.provider_txn_id,
                user_id=order.user_id,
                detail={
                    "existing_order_no": other.order_no,
                    "existing_user_id": other.user_id,
                    "incoming_order_no": order.order_no,
                    "incoming_user_id": order.user_id,
                },
            )
            raise PaymentConflictError(
                f"渠道交易号 {result.provider_txn_id} 已核销到订单 {other.order_no}"
            ) from exc

    # 同单被并发回调抢先核销：重新读单确认后按幂等处理
    refreshed = db.get(Order, order.id)
    if refreshed and refreshed.fulfilled_at is not None:
        record_audit(
            db,
            channel=order.payment_channel,
            event_type=EVT_DUPLICATE_NOTIFICATION,
            result="ignored",
            order_no=refreshed.order_no,
            provider_txn_id=result.provider_txn_id,
            user_id=refreshed.user_id,
        )
        return False

    # 未预期的约束冲突：不要吞掉，抛 500 触发排查
    raise exc


def _safe_raw(result: PaymentResult) -> str:
    import json

    try:
        return json.dumps(result.raw, ensure_ascii=False)[:8000]
    except (TypeError, ValueError):
        return ""


def handle_callback(
    db: Session, channel: str, headers: dict[str, str], body: bytes
) -> Order:
    """验签 + 定位订单 + 幂等核销。

    - 验签失败：记录审计后抛 ``PaymentVerifyError``（路由返回 401）；
    - 订单不存在：记录审计后抛 ``PaymentError``（路由返回 4xx，避免无意义重放）；
    - 同单并发：仅一次核销，其余幂等成功返回；
    - SQLite 锁错误：有限退避重试后重新读单，保证不重复发货。
    """
    if not provider_exists(channel):
        raise PaymentError(f"支付渠道未启用：{channel}")

    result = _verify_callback(db, channel, headers, body)
    order_no = _extract_order_no(result)

    last_locked_exc: OperationalError | None = None
    for attempt in range(1, _LOCK_RETRY_MAX + 1):
        order = _locate_order(db, channel, result, order_no)
        if not order:
            record_audit(
                db,
                channel=channel,
                event_type=EVT_ORDER_NOT_FOUND,
                result="rejected",
                order_no=order_no or None,
                provider_txn_id=result.provider_txn_id,
                detail={"order_no_present": bool(order_no)},
            )
            raise PaymentError("回调对应订单不存在")
        if order.payment_channel != channel:
            # 不记 order_no 之外的信息；这是配置/路由异常
            record_audit(
                db,
                channel=channel,
                event_type=EVT_TXN_CONFLICT,
                result="rejected",
                order_no=order.order_no,
                provider_txn_id=result.provider_txn_id,
                user_id=order.user_id,
                detail={"reason": "channel_mismatch", "order_channel": order.payment_channel},
            )
            raise PaymentVerifyError("订单渠道与回调渠道不一致")

        try:
            fulfill_order(db, order, result)
            db.refresh(order)
            return order
        except OperationalError as exc:
            db.rollback()
            msg = str(exc).lower()
            if "locked" in msg or "busy" in msg:
                last_locked_exc = exc
                time.sleep(_LOCK_RETRY_BASE_SLEEP * attempt)
                continue
            raise
        # PaymentError / PaymentConflictError / PaymentVerifyError 直接向上抛

    logger.warning(
        "支付回调在 %d 次重试后仍因数据库锁失败 channel=%s order=%s",
        _LOCK_RETRY_MAX,
        channel,
        order_no,
    )
    raise last_locked_exc  # type: ignore[misc]


def _verify_callback(
    db: Session, channel: str, headers: dict[str, str], body: bytes
) -> PaymentResult:
    provider = get_provider(channel)
    try:
        return provider.verify_callback(headers, body)
    except PaymentVerifyError as exc:
        # 验签失败：不解析不可信 body 取订单/交易信息，仅记录渠道与原因
        record_audit(
            db,
            channel=channel,
            event_type=EVT_SIGNATURE_FAILED,
            result="rejected",
            detail={"reason": str(exc)[:120]},
        )
        raise


def _locate_order(
    db: Session, channel: str, result: PaymentResult, order_no: str
) -> Order | None:
    if order_no:
        order = _locked_order_by_no(db, order_no)
        if order:
            return order
    # 渠道交易号反查（恢复/补单/重放场景）
    if result.provider_txn_id:
        return _locked_order_by_txn(db, channel, result.provider_txn_id)
    return None


def _extract_order_no(result: PaymentResult) -> str:
    return str(result.raw.get("order_no", ""))


def _locked_order_by_no(db: Session, order_no: str) -> Order | None:
    return db.scalar(_for_update(db, select(Order).where(Order.order_no == order_no)))


def _locked_order_by_txn(db: Session, channel: str, txn_id: str) -> Order | None:
    return db.scalar(
        _for_update(
            db,
            select(Order).where(
                Order.payment_channel == channel,
                Order.provider_txn_id == txn_id,
            ),
        )
    )


def restore_purchase(db: Session, user: User, channel: str, receipt_data: str) -> Order:
    """IAP 恢复购买：服务端校验票据，映射套餐，落单并开通。

    以 `original_transaction_id` 为幂等键：同一订阅在不同设备恢复只会绑定到会员一次。
    """
    if not provider_exists(channel):
        raise PaymentError(f"支付渠道未启用：{channel}")
    provider = get_provider(channel)
    result = provider.verify_receipt(receipt_data)
    if not result.success:
        raise PaymentError("票据校验未通过")

    product_id = result.product_id
    plan_code = _plan_code_for_product(channel, product_id)
    if not plan_code:
        raise PaymentError(f"未知渠道商品：{product_id}")
    item = PLAN_CATALOG[plan_code]

    orig_id = result.original_transaction_id or result.provider_txn_id

    # 幂等 1：已用该订阅绑定过会员，直接返回（可能绑在别的订单上）
    if orig_id:
        existing_m = db.scalar(
            select(Membership).where(
                Membership.payment_channel == channel,
                Membership.provider_subscription_id == orig_id,
            )
        )
        if existing_m:
            # 该订阅已绑定到其他用户：票据归属他人，拒绝（防止越权恢复/信息泄露）。
            # 无论其会员是否 active 都拒绝，也避免命中 provider_subscription_id 唯一约束。
            if existing_m.user_id != user.id:
                raise PaymentVerifyError("该票据属于其他用户")
            if existing_m.is_active:
                order = db.scalar(
                    select(Order).where(Order.order_no == existing_m.order_id)
                )
                if order:
                    return order

    # 幂等 2：该渠道交易号已落单
    order = db.scalar(
        select(Order).where(
            Order.payment_channel == channel,
            Order.provider_txn_id == result.provider_txn_id,
        )
    )
    if order:
        # 确保归属当前用户（防止拿别人票据恢复）
        if order.user_id != user.id:
            raise PaymentVerifyError("该票据属于其他用户")
        fulfill_order(db, order, result)
        db.refresh(order)
        return order

    order = Order(
        order_no=_gen_order_no(),
        user_id=user.id,
        plan=item["plan"],
        plan_code=plan_code,
        duration_days=int(item["duration_days"]),
        amount_cents=int(item["amount_cents"]),
        currency=item.get("currency", "CNY"),
        payment_channel=channel,
        status="pending",
        provider_txn_id=result.provider_txn_id,
    )
    db.add(order)
    try:
        db.flush()
    except IntegrityError:
        # 并发恢复同一渠道交易号：另一请求已落单，回查后按幂等处理
        db.rollback()
        order = db.scalar(
            select(Order).where(
                Order.payment_channel == channel,
                Order.provider_txn_id == result.provider_txn_id,
            )
        )
        if not order:
            raise PaymentError("恢复购买失败，请重试") from None
        if order.user_id != user.id:
            raise PaymentVerifyError("该票据属于其他用户")
        fulfill_order(db, order, result)
        db.refresh(order)
        return order
    fulfill_order(db, order, result)
    db.refresh(order)
    return order


def _plan_code_for_product(channel: str, product_id: str | None) -> str | None:
    for code, item in PLAN_CATALOG.items():
        if item.get("provider_product_id", {}).get(channel) == product_id:
            return code
    return None


def get_order(db: Session, user: User, order_no: str) -> Order:
    order = db.scalar(select(Order).where(Order.order_no == order_no))
    if not order or order.user_id != user.id:
        raise PaymentError("订单不存在")
    return order


def order_status_view(order: Order, user: User) -> dict:
    m = user.membership
    return {
        "order_no": order.order_no,
        "status": order.status,
        "is_active": bool(m and m.is_active and _not_expired(m)),
        "expire_at": m.expire_at if m else None,
    }


def _not_expired(m: Membership) -> bool:
    if not m.expire_at:
        return False
    exp = m.expire_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp > _now()
