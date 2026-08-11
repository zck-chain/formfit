"""支付审计日志：结构化记录回调核销过程中的安全/对账事件。

设计原则：
- 只记可对账的最小字段，绝不写密钥、签名、receipt、原始完整回调或用户敏感数据；
- 交易号只保留首尾各 4 位的脱敏提示（`_txn_hint`），完整交易号已在订单表中可查；
- 审计写入失败不得影响回调主流程（吞异常并告警），但主流程的回滚必须先于审计提交，
  避免把失败的核销改动顺带提交。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.payment_audit import PaymentAuditEvent

logger = logging.getLogger(__name__)

# 事件类型常量（与模型 AUDIT_EVENTS 对应）
EVT_SIGNATURE_FAILED = "signature_failed"
EVT_AMOUNT_MISMATCH = "amount_mismatch"
EVT_CURRENCY_MISMATCH = "currency_mismatch"
EVT_TXN_CONFLICT = "txn_conflict"
EVT_DUPLICATE_NOTIFICATION = "duplicate_notification"
EVT_FULFILLED = "fulfilled"
EVT_FAILED = "failed"
EVT_ORDER_NOT_FOUND = "order_not_found"
EVT_IAP_CALLBACK_REJECTED = "iap_callback_rejected"


def _txn_hint(txn_id: str | None) -> str | None:
    """交易号脱敏：保留首尾各 4 位，中间用 … 代替；不足 8 位整体遮蔽。"""
    if not txn_id:
        return None
    s = str(txn_id)
    if len(s) < 8:
        return "****"
    return f"{s[:4]}…{s[-4:]}"


def record_audit(
    db: Session,
    *,
    channel: str,
    event_type: str,
    result: str = "",
    order_no: str | None = None,
    provider_txn_id: str | None = None,
    user_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """写入一条审计事件，独立提交；任何异常都被吞掉以免影响回调主流程。

    调用方必须确保传入时会话没有待提交的核销改动（成功路径应在主事务提交后调用；
    失败/冲突路径应先 rollback 再调用），避免审计提交顺带写入未完成的业务改动。
    """
    try:
        event = PaymentAuditEvent(
            channel=channel,
            event_type=event_type,
            result=result,
            order_no=order_no,
            provider_txn_hint=_txn_hint(provider_txn_id),
            user_id=user_id,
            detail=detail or {},
        )
        db.add(event)
        db.commit()
    except Exception:  # noqa: BLE001  审计失败不能影响支付主流程
        db.rollback()
        logger.warning(
            "支付审计事件写入失败 channel=%s event=%s order=%s",
            channel,
            event_type,
            order_no,
            exc_info=True,
        )
