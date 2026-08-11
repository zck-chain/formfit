"""支付审计事件模型。

仅记录可用于对账/排查的最小、安全字段：渠道、事件类型、订单号、交易号脱敏提示、
结果、小尺寸 JSON 详情。严禁写入密钥、签名、receipt、原始回调体或用户敏感数据
（见 `app/payment/audit.py` 的 `_txn_hint` 与白名单详情构造）。
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# 事件类型（与 app.payment.audit 中的常量保持一致）
AUDIT_EVENTS = (
    "signature_failed",        # 验签失败
    "amount_mismatch",         # 金额与订单不一致
    "currency_mismatch",       # 币种与订单不一致
    "txn_conflict",            # 同渠道交易号核销到不同订单/用户
    "duplicate_notification",  # 已核销订单的重复回调（幂等跳过）
    "fulfilled",               # 核销成功
    "failed",                  # 渠道明确通知失败
    "order_not_found",         # 回调对应订单不存在
    "iap_callback_rejected",   # Apple S2S 回调未启用，安全拒绝
)


class PaymentAuditEvent(Base):
    __tablename__ = "payment_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    channel: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    # 结果口径：success / rejected / ignored / error
    result: Mapped[str] = mapped_column(String(16), default="")

    # 自有订单号可直接记录（不泄漏自增 id）；交易号仅存脱敏提示
    order_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider_txn_hint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # 白名单构造的小尺寸详情，绝不含签名/密钥/原始回调
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
