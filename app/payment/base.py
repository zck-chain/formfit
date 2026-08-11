"""支付渠道抽象接口与归一化结果。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PaymentResult:
    """渠道验签通过后的归一化支付事实。

    `success=False` 表示渠道明确通知失败（非验签失败——验签失败应直接抛异常）。
    `provider_txn_id` 是渠道侧交易号，全局用于回调幂等去重。
    """

    success: bool
    provider_txn_id: str
    # IAP 恢复购买时，本地尚无订单，需由渠道返回商品 id 以映射套餐
    product_id: str | None = None
    amount_cents: int | None = None
    currency: str | None = None
    # 订阅类渠道（Apple）的原始交易号，用于绑定 Membership 以便恢复/续期
    original_transaction_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentProvider(ABC):
    """支付渠道最小接口。各渠道实现必须自己保证验签安全。"""

    #: 渠道标识，与 Order.payment_channel 一致
    name: str = ""

    @abstractmethod
    def create_payment(self, order: "OrderLike") -> dict[str, Any]:  # type: ignore[name-defined]
        """服务端下单/预下单，返回给客户端的支付凭据（支付串/参数/商品 id）。"""

    @abstractmethod
    def verify_callback(self, headers: dict[str, str], body: bytes) -> PaymentResult:
        """校验异步回调签名并解析。验签失败必须抛 `PaymentVerifyError`。"""

    def verify_receipt(self, receipt_data: str) -> PaymentResult:
        """服务端票据校验（IAP 恢复购买/主动校验）。不支持的渠道抛 NotImplementedError。"""
        raise NotImplementedError(f"{self.name} 不支持服务端票据校验")

    def refund(self, provider_txn_id: str) -> bool:
        """退款。不支持的渠道抛 NotImplementedError。"""
        raise NotImplementedError(f"{self.name} 不支持退款")


class PaymentVerifyError(Exception):
    """回调/票据验签失败或内容非法。"""


# 避免运行期循环 import，用结构化参数类型
class OrderLike:
    order_no: str
    plan_code: str
    amount_cents: int
    currency: str
    duration_days: int
