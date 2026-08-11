"""支付业务服务：下单、回调核销、会员开通/续期、恢复购买。

核销幂等有三道闸门：
1. `(payment_channel, provider_txn_id)` 唯一约束——同渠道同交易号只能落一笔订单；
2. `Order.fulfilled_at` 为空才开通——重复回调直接返回，不重复加时长；
3. 会员时长在事务内计算并提交，行级状态保证不会并发叠加。
"""
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Membership, Order, User
from app.payment import PaymentResult, get_provider, provider_exists
from app.payment.base import PaymentVerifyError
from app.schemas.payment import PLAN_CATALOG


class PaymentError(Exception):
    """业务层支付错误（参数/状态不合法），由路由转成 4xx。"""


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
    """Postgres/MySQL 下加行锁 `FOR UPDATE`，串行化同一订单的并发回调；
    SQLite 直接降级（其写事务本身串行）。"""
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
        m = Membership(user_id=user_id, plan="free", is_active=False)
        db.add(m)
        db.flush()
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


def fulfill_order(db: Session, order: Order, result: PaymentResult) -> bool:
    """在事务内把订单标记成功并核销。返回 True 表示本次真的开通，False 表示重复回调幂等跳过。"""
    if order.fulfilled_at is not None or order.status in ("fulfilled",):
        return False
    if result.success and order.status not in ("paid", "pending"):
        # 已 failed/refunded 的订单不允许被回调翻案
        return False

    # 金额以服务端订单为准；渠道若回传金额且不一致，直接拒绝（防短款支付/篡改）
    if result.success and result.amount_cents is not None and int(result.amount_cents) != order.amount_cents:
        raise PaymentError(
            f"回调金额 {result.amount_cents} 与订单金额 {order.amount_cents} 不一致"
        )

    now = _now()
    if not result.success:
        order.status = "failed"
        order.raw_callback = _safe_raw(result)
        db.commit()
        return False

    order.status = "paid"
    order.paid_at = order.paid_at or now
    if result.provider_txn_id and not order.provider_txn_id:
        order.provider_txn_id = result.provider_txn_id
    order.raw_callback = _safe_raw(result)

    _apply_membership(
        db,
        user_id=order.user_id,
        plan=order.plan,
        duration_days=order.duration_days,
        channel=order.payment_channel,
        order_no=order.order_no,
        provider_subscription_id=result.original_transaction_id,
    )

    order.status = "fulfilled"
    order.fulfilled_at = now
    try:
        db.commit()
    except IntegrityError:
        # 并发回调下 provider_txn_id 唯一约束或其它约束冲突——回滚并按幂等处理
        db.rollback()
        return False
    return True


def _safe_raw(result: PaymentResult) -> str:
    import json

    try:
        return json.dumps(result.raw, ensure_ascii=False)[:8000]
    except (TypeError, ValueError):
        return ""


def handle_callback(
    db: Session, channel: str, headers: dict[str, str], body: bytes
) -> Order:
    """验签 + 定位订单 + 幂等核销。找不到订单/验签失败抛异常，路由据此返回非 2xx，
    让渠道重试；验签通过但已核销则正常返回（渠道停止重放）。"""
    if not provider_exists(channel):
        raise PaymentError(f"支付渠道未启用：{channel}")
    provider = get_provider(channel)
    result = provider.verify_callback(headers, body)

    order = _locked_order_by_no(db, _extract_order_no(result))
    if not order:
        # 渠道交易号也能反查（恢复/补单场景）
        if result.provider_txn_id:
            order = _locked_order_by_txn(db, channel, result.provider_txn_id)
    if not order:
        raise PaymentError("回调对应订单不存在")
    if order.payment_channel != channel:
        raise PaymentVerifyError("订单渠道与回调渠道不一致")

    fulfill_order(db, order, result)
    db.refresh(order)
    return order


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
