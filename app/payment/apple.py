"""Apple App Store 内购（IAP）服务端票据校验。

首发若为 iOS，客户端完成购买后把 base64 receipt 提交到 `/restore`，
服务端调用 Apple `verifyReceipt` 校验，解析出 product_id / original_transaction_id
后映射到本地套餐并开通会员。相比仅依赖客户端回调，票据由服务端直连 Apple 校验，防伪造。

说明：
- 生产/沙箱端点按 `apple_production` 选择；遇到 21007 自动回退沙箱（TestFlight 常见）。
- Apple S2S 通知（V2 JWS）的证书链校验需要内置 Apple Root CA 并校验 x5c 链，
  首发渠道确认后再补齐；当前默认拒绝未校验的回调（安全默认，伪造不能开通）。
"""
from typing import Any

import httpx

from app.core.config import settings
from app.payment.base import OrderLike, PaymentProvider, PaymentResult, PaymentVerifyError

_PRODUCTION_URL = "https://buy.itunes.apple.com/verifyReceipt"
_SANDBOX_URL = "https://sandbox.itunes.apple.com/verifyReceipt"


class AppleIAPProvider(PaymentProvider):
    name = "apple"

    def create_payment(self, order: OrderLike) -> dict[str, Any]:
        # IAP 由客户端用 product_id 发起 SKPayment；服务端只回商品 id
        product_id = self._product_id(order.plan_code)
        if not product_id:
            raise PaymentVerifyError(f"套餐 {order.plan_code} 未配置 Apple 商品 ID")
        return {"provider": "apple", "product_id": product_id}

    @staticmethod
    def _product_id(plan_code: str) -> str | None:
        from app.schemas.payment import PLAN_CATALOG

        return PLAN_CATALOG.get(plan_code, {}).get("provider_product_id", {}).get("apple")

    def _verify(self, receipt_data: str, url: str) -> dict[str, Any]:
        resp = httpx.post(
            url,
            json={
                "receipt-data": receipt_data,
                "password": settings.apple_shared_secret,
                "exclude-old-transactions": True,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()

    def verify_receipt(self, receipt_data: str) -> PaymentResult:
        if not settings.apple_shared_secret:
            raise PaymentVerifyError("未配置 Apple 共享密钥（APPLE_SHARED_SECRET）")

        primary = _PRODUCTION_URL if settings.apple_production else _SANDBOX_URL
        fallback = _SANDBOX_URL if settings.apple_production else _PRODUCTION_URL

        data = self._verify(receipt_data, primary)
        # 21007：receipt 来自沙箱但发到了生产，反之 21008 → 回退另一端
        if data.get("status") == 21007:
            data = self._verify(receipt_data, fallback)

        status = data.get("status")
        if status != 0:
            raise PaymentVerifyError(f"Apple 票据校验失败，status={status}")

        if settings.apple_bundle_id:
            bundle_id = (data.get("receipt") or {}).get("bundle_id")
            if bundle_id != settings.apple_bundle_id:
                raise PaymentVerifyError("票据 bundle_id 不匹配，疑似跨 App 伪造")

        info = self._extract_latest(data)
        if not info:
            raise PaymentVerifyError("票据中未找到有效内购交易")

        product_id = info.get("product_id")
        if not self._plan_code_for_product(product_id):
            raise PaymentVerifyError(f"未知的 Apple 商品：{product_id}")

        return PaymentResult(
            success=True,
            provider_txn_id=str(info.get("transaction_id")),
            product_id=product_id,
            original_transaction_id=info.get("original_transaction_id"),
            raw=data,
        )

    @staticmethod
    def _extract_latest(data: dict[str, Any]) -> dict[str, Any] | None:
        # 自动续期订阅在 latest_receipt_info；非消耗型在 receipt.in_app
        latest = data.get("latest_receipt_info") or []
        if isinstance(latest, list) and latest:
            # 取 expires_date 最大（最近一次续期）
            return max(latest, key=lambda t: int(t.get("expires_date_ms", 0)))
        in_app = (data.get("receipt") or {}).get("in_app") or []
        if in_app:
            return in_app[-1]
        return None

    @staticmethod
    def _plan_code_for_product(product_id: str | None) -> str | None:
        from app.schemas.payment import PLAN_CATALOG

        for code, item in PLAN_CATALOG.items():
            if item.get("provider_product_id", {}).get("apple") == product_id:
                return code
        return None

    def verify_callback(self, headers: dict[str, str], body: bytes) -> PaymentResult:
        # Apple V2 通知为 JWS（signedPayload），需校验 x5c 证书链至 Apple Root CA。
        # 首发渠道确认后补齐；默认拒绝，避免未验签即开通。
        raise PaymentVerifyError(
            "Apple S2S 回调证书链校验尚未启用；请通过客户端票据校验（/restore）开通"
        )
