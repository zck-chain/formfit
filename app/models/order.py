"""支付订单模型。

订单是一次付费意图的不可变事实记录；会员开通/续期由订单的 `paid` 事件驱动，
通过 `fulfilled_at` 做核销幂等（同一笔订单最多开通一次）。
"""
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# 订单状态机
# pending   -> 已创建，等待支付/回调
# paid      -> 收到渠道成功回调并通过验签，等待/已核销
# fulfilled -> 会员已开通或续期（终态，成功）
# failed    -> 渠道明确失败或超时（终态，失败）
# refunded  -> 已退款，会员权益被回收（终态）
ORDER_STATUSES = ("pending", "paid", "fulfilled", "failed", "refunded")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        # 渠道侧交易号唯一，用于回调幂等去重
        UniqueConstraint("payment_channel", "provider_txn_id", name="uq_order_provider_txn"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 对外暴露的订单号（不泄漏自增 id）
    order_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    # 商品：与会员 plan 对齐（free/pro），plan_code 标识具体套餐
    plan: Mapped[str] = mapped_column(String(32), default="pro")
    plan_code: Mapped[str] = mapped_column(String(64))
    duration_days: Mapped[int] = mapped_column(Integer)

    # 金额用整数“分”存储，避免浮点误差；currency 为 ISO 4217 三位码
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="CNY")

    payment_channel: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)

    # 渠道侧交易号/订单号（回调时回填）
    provider_txn_id: Mapped[str | None] = mapped_column(String(191), nullable=True)
    # 渠道原始回调载荷，仅用于排查/对账，不参与逻辑
    raw_callback: Mapped[str | None] = mapped_column(Text, nullable=True)

    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fulfilled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
