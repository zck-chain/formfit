"""沙箱支付渠道。

用于本地与联调环境跑通 下单→支付→回调→开通 完整链路，不接真实资金。
回调采用 HMAC-SHA256 签名，签名串为 `{order_no}.{status}.{txn_id}`，
与真实渠道验签路径一致，可验证“伪造/重放不能开通”。
"""
import hashlib
import hmac
from typing import Any

from app.core.config import settings
from app.payment.base import OrderLike, PaymentProvider, PaymentResult, PaymentVerifyError


class SandboxProvider(PaymentProvider):
    name = "sandbox"

    def _sign(self, order_no: str, status: str, amount_cents: int, txn_id: str) -> str:
        # 签名串必须覆盖金额，否则客户端可篡改 amount_cents 而签名仍校验通过
        msg = f"{order_no}.{status}.{amount_cents}.{txn_id}".encode("utf-8")
        return hmac.new(
            settings.sandbox_secret.encode("utf-8"), msg, hashlib.sha256
        ).hexdigest()

    def create_payment(self, order: OrderLike) -> dict[str, Any]:
        # 给客户端一个可直接触发成功回调的地址与签名（仅沙箱）
        txn_id = f"sb_{order.order_no}"
        pay_url = (
            f"{settings.payment_callback_base_url}/api/payment/callback/sandbox"
        )
        return {
            "pay_url": pay_url,
            "order_no": order.order_no,
            "status": "pending",
            # 沙箱“支付”所需参数；真实渠道绝不会把签名密钥交给客户端，
            # 这里仅为本地端到端联调，密钥本身是 dev 值。
            "sandbox": {
                "txn_id": txn_id,
                "amount_cents": order.amount_cents,
                "sign": self._sign(order.order_no, "success", order.amount_cents, txn_id),
            },
        }

    def verify_callback(self, headers: dict[str, str], body: bytes) -> PaymentResult:
        import json

        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise PaymentVerifyError("回调体不是合法 JSON") from exc

        order_no = data.get("order_no")
        txn_id = data.get("txn_id")
        status = data.get("status", "success")
        amount_cents = data.get("amount_cents")
        sig = headers.get("x-sandbox-signature") or data.get("sign")
        if not order_no or not txn_id or amount_cents is None or not sig:
            raise PaymentVerifyError("回调缺少必要字段")

        try:
            amount_cents = int(amount_cents)
        except (TypeError, ValueError) as exc:
            raise PaymentVerifyError("回调金额非法") from exc

        expected = self._sign(order_no, status, amount_cents, txn_id)
        if not hmac.compare_digest(expected, sig):
            raise PaymentVerifyError("沙箱回调签名校验失败")

        return PaymentResult(
            success=status == "success",
            provider_txn_id=str(txn_id),
            amount_cents=data.get("amount_cents"),
            currency=data.get("currency"),
            raw=data,
        )

    def verify_receipt(self, receipt_data: str) -> PaymentResult:
        # 沙箱票据格式：txn_id:product_id:sign(sign over txn_id.product_id)
        parts = receipt_data.split(":")
        if len(parts) != 3:
            raise PaymentVerifyError("沙箱票据格式非法")
        txn_id, product_id, sig = parts
        msg = f"{txn_id}.{product_id}".encode("utf-8")
        expected = hmac.new(
            settings.sandbox_secret.encode("utf-8"), msg, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise PaymentVerifyError("沙箱票据签名失败")
        return PaymentResult(
            success=True,
            provider_txn_id=txn_id,
            product_id=product_id,
            # 沙箱把交易号同时作为订阅原始 ID，便于恢复购买幂等绑定
            original_transaction_id=txn_id,
            raw={"receipt": receipt_data},
        )
