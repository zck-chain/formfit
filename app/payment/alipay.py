"""支付宝支付渠道（RSA2 / SHA256withRSA）。

- create_payment：本地用商户应用私钥对 App 支付参数签名，返回 orderStr 给客户端
  （支付宝 App 支付由客户端凭 orderStr 唤起支付宝，服务端无需请求支付宝网关，
  因此本方法不发起任何 HTTP 调用）。
- verify_callback：用支付宝公钥校验异步通知（notify_url）的 RSA2 签名；
  伪造或篡改的回调一律 PaymentVerifyError，不能核销。

凭证未配置时 create_payment/verify_callback 抛 PaymentVerifyError，绝不静默返回假成功。
拿到真实凭证后填入 .env 即可联调，无需改代码。
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.payment import _crypto
from app.payment.base import (
    OrderLike,
    PaymentProvider,
    PaymentResult,
    PaymentVerifyError,
)

# 支付宝交易成功状态：TRADE_SUCCESS（即时到账）/ TRADE_FINISHED（不可退款结束）
_TRADE_SUCCESS_STATES = {"TRADE_SUCCESS", "TRADE_FINISHED"}


def _build_sign_string(params: dict[str, str]) -> str:
    """构造待签名字符串：按 key 字典序排序，拼成 key=value&...，值不做 URL 编码。

    空值不参与签名（与支付宝开放平台规范一致）。
    """
    items = sorted(
        ((k, v) for k, v in params.items() if v is not None and v != ""),
        key=lambda kv: kv[0],
    )
    return "&".join(f"{k}={v}" for k, v in items)


class AlipayProvider(PaymentProvider):
    name = "alipay"

    # ---------- 下单（App 支付串）----------
    def create_payment(self, order: OrderLike) -> dict[str, Any]:
        missing = self._missing_create_credentials()
        if missing:
            raise PaymentVerifyError(f"支付宝未配置：缺少 {', '.join(missing)}")

        biz_content = {
            "out_trade_no": order.order_no,
            "total_amount": f"{order.amount_cents / 100:.2f}",
            "subject": f"FormFit {order.plan_code}",
            "product_code": "QUICK_MSECURITY_PAY",
        }
        params: dict[str, str] = {
            "app_id": settings.alipay_app_id,
            "method": "alipay.trade.app.pay",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "notify_url": settings.alipay_callback_url,
            "biz_content": json.dumps(
                biz_content, separators=(",", ":"), ensure_ascii=False
            ),
        }
        try:
            params["sign"] = _crypto.rsa_sign_sha256(
                settings.alipay_private_key, _build_sign_string(params)
            )
        except _crypto.CryptoError as exc:
            raise PaymentVerifyError(f"支付宝下单签名失败：{exc}") from exc

        # orderStr：所有参数（含 sign）做 URL 编码，客户端直接传给支付宝 SDK
        order_str = urllib.parse.urlencode(
            sorted(params.items()), quote_via=urllib.parse.quote
        )
        return {
            "provider": "alipay",
            "trade_type": "APP",
            "order_no": order.order_no,
            "order_str": order_str,
        }

    # ---------- 异步回调验签 ----------
    def verify_callback(self, headers: dict[str, str], body: bytes) -> PaymentResult:
        if not settings.alipay_public_key:
            raise PaymentVerifyError("支付宝未配置：缺少 ALIPAY_PUBLIC_KEY，无法验签")

        try:
            text = body.decode("utf-8")
            parsed = urllib.parse.parse_qs(text, keep_blank_values=True)
        except UnicodeDecodeError as exc:
            raise PaymentVerifyError("支付宝回调体编码非法") from exc

        # parse_qs 把每个值解析成 list；支付宝通知每个字段都是单值
        data = {k: v[0] for k, v in parsed.items() if v}
        sign = data.pop("sign", None)
        data.pop("sign_type", None)  # sign_type 不参与验签
        if not sign:
            raise PaymentVerifyError("支付宝回调缺少 sign")

        message = _build_sign_string(data)
        if not _crypto.rsa_verify_sha256(settings.alipay_public_key, message, sign):
            raise PaymentVerifyError("支付宝回调签名校验失败")

        trade_status = data.get("trade_status", "")
        success = trade_status in _TRADE_SUCCESS_STATES

        # 金额校验由服务层 fulfill_order 与订单金额比对，这里只回传
        amount_cents = self._parse_amount(data.get("total_amount"))
        return PaymentResult(
            success=success,
            provider_txn_id=str(data.get("trade_no") or data.get("out_trade_no") or ""),
            amount_cents=amount_cents,
            currency=data.get("currency") or "CNY",
            # out_trade_no 即本地订单号，服务层据此定位订单
            raw={"order_no": data.get("out_trade_no"), **data},
        )

    @staticmethod
    def _missing_create_credentials() -> list[str]:
        missing = []
        if not settings.alipay_app_id:
            missing.append("ALIPAY_APP_ID")
        if not settings.alipay_private_key:
            missing.append("ALIPAY_PRIVATE_KEY")
        if not settings.alipay_public_key:
            missing.append("ALIPAY_PUBLIC_KEY")
        if not settings.alipay_callback_url:
            missing.append("ALIPAY_CALLBACK_URL")
        return missing

    @staticmethod
    def _parse_amount(total_amount: str | None) -> int | None:
        if not total_amount:
            return None
        try:
            return int(round(float(total_amount) * 100))
        except (TypeError, ValueError):
            return None
