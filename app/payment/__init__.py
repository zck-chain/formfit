"""支付渠道适配层。

每个渠道实现一个 `PaymentProvider`，封装：下单、回调验签、服务端票据校验（IAP 恢复购买）、
退款。核心服务只依赖这个抽象，新增渠道只需实现接口并在 `registry` 注册。

所有“来自渠道的事实”先经 `verify_*` 验签并归一化为 `PaymentResult`，
再交给服务层做幂等核销——验签与权限逻辑分离，便于测试与安全评审。
"""
from app.payment.base import PaymentProvider, PaymentResult
from app.payment.registry import get_provider, provider_exists, supported_channels

__all__ = [
    "PaymentProvider",
    "PaymentResult",
    "get_provider",
    "provider_exists",
    "supported_channels",
]
