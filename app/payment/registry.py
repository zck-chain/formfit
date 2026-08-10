"""支付渠道注册表：按配置启用渠道并按需实例化。"""
from functools import lru_cache

from app.core.config import settings
from app.payment.apple import AppleIAPProvider
from app.payment.base import PaymentProvider
from app.payment.sandbox import SandboxProvider

# 渠道名 -> 构造器；新增渠道在此登记
_PROVIDER_FACTORIES = {
    "sandbox": SandboxProvider,
    "apple": AppleIAPProvider,
}


@lru_cache(maxsize=None)
def _enabled() -> dict[str, PaymentProvider]:
    names = [c.strip().lower() for c in settings.payment_channels.split(",") if c.strip()]
    instances: dict[str, PaymentProvider] = {}
    for name in names:
        factory = _PROVIDER_FACTORIES.get(name)
        if not factory:
            # 不静默忽略未知渠道，避免配置打错后误以为已接入
            raise ValueError(f"未知或未实现的支付渠道：{name}")
        instances[name] = factory()
    return instances


def supported_channels() -> list[str]:
    return list(_enabled().keys())


def provider_exists(channel: str) -> bool:
    return channel in _enabled()


def get_provider(channel: str) -> PaymentProvider:
    providers = _enabled()
    if channel not in providers:
        raise KeyError(f"支付渠道未启用：{channel}")
    return providers[channel]
