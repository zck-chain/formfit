"""微信支付渠道（APIv3）。

- create_payment：服务端用商户私钥签名 Authorization 头，调用微信 V3 统一下单接口
  （/v3/pay/transactions/app）拿到 prepay_id，再对客户端 App 支付参数二次签名返回。
  HTTP 客户端可注入（构造函数 `client`），便于测试；无凭证时在发请求前直接抛错，
  不会发起任何真实网络调用。
- verify_callback：用微信支付平台证书/公钥校验 Wechatpay-Signature（RSA-SHA256），
  再用 APIv3 密钥做 AES-256-GCM 解密 resource，得到支付事实。

本模块实现 APP 支付（Flutter iOS/Android 端）。JSAPI/Native 支付可在拿到凭证后
按相同签名框架扩展 trade_type，不影响核销与回调链路。无真实凭证，未做网关联调。
"""
from __future__ import annotations

import base64
import json
import secrets
import time
from typing import Any

import httpx

from app.core.config import settings
from app.payment import _crypto
from app.payment.base import (
    OrderLike,
    PaymentProvider,
    PaymentResult,
    PaymentVerifyError,
)

_GATEWAY = "https://api.mch.weixin.qq.com"
# 回调时间戳允许的偏差（秒），超过视为异常/重放
_TIMESTAMP_TOLERANCE_SECONDS = 300


def _now_ts() -> str:
    return str(int(time.time()))


def _nonce() -> str:
    # token_urlsafe(12) ≈ 16 字符，满足微信随机串要求
    return secrets.token_urlsafe(12)


class WechatProvider(PaymentProvider):
    name = "wechat"

    def __init__(self, client: httpx.Client | None = None, gateway: str = _GATEWAY) -> None:
        # 生产环境留空 client：在真正下单时惰性创建（且仅在凭证齐全时）。
        self._client = client
        self._gateway = gateway.rstrip("/")

    # ---------- 下单 ----------
    def create_payment(self, order: OrderLike) -> dict[str, Any]:
        missing = self._missing_create_credentials()
        if missing:
            raise PaymentVerifyError(f"微信支付未配置：缺少 {', '.join(missing)}")

        path = "/v3/pay/transactions/app"
        payload = {
            "appid": settings.wechat_app_id,
            "mchid": settings.wechat_mch_id,
            "description": f"FormFit {order.plan_code}",
            "out_trade_no": order.order_no,
            "notify_url": settings.wechat_notify_url,
            "amount": {"total": order.amount_cents, "currency": order.currency or "CNY"},
        }
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        headers = {
            "Authorization": self._authorization("POST", path, body),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=15.0)
        try:
            resp = client.post(f"{self._gateway}{path}", content=body, headers=headers)
            resp.raise_for_status()
            prepay_id = resp.json().get("prepay_id")
        finally:
            if owns_client:
                client.close()

        if not prepay_id:
            raise PaymentVerifyError("微信下单未返回 prepay_id")
        return self._build_app_pay_params(prepay_id, order.order_no)

    def _build_app_pay_params(self, prepay_id: str, order_no: str) -> dict[str, Any]:
        timestamp = _now_ts()
        nonce = _nonce()
        # APP 支付客户端调起签名：appid\ntimestamp\nnonce\nprepayid\n
        message = f"{settings.wechat_app_id}\n{timestamp}\n{nonce}\n{prepay_id}\n"
        try:
            sign = _crypto.rsa_sign_sha256(settings.wechat_mch_private_key, message)
        except _crypto.CryptoError as exc:
            raise PaymentVerifyError(f"微信客户端支付参数签名失败：{exc}") from exc
        return {
            "provider": "wechat",
            "trade_type": "APP",
            "order_no": order_no,
            "appid": settings.wechat_app_id,
            "partnerid": settings.wechat_mch_id,
            "prepayid": prepay_id,
            "package": "Sign=WXPay",
            "noncestr": nonce,
            "timestamp": timestamp,
            "sign": sign,
        }

    def _authorization(self, method: str, url_path: str, body: str) -> str:
        timestamp = _now_ts()
        nonce = _nonce()
        # 微信 V3 请求签名串：HTTP方法\nURL\n时间戳\n随机串\n请求报文\n
        message = f"{method}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n"
        try:
            signature = _crypto.rsa_sign_sha256(settings.wechat_mch_private_key, message)
        except _crypto.CryptoError as exc:
            raise PaymentVerifyError(f"微信请求签名失败：{exc}") from exc
        return (
            f'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{settings.wechat_mch_id}",'
            f'nonce_str="{nonce}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{settings.wechat_mch_serial_no}",'
            f'signature="{signature}"'
        )

    # ---------- 异步回调验签 + 解密 ----------
    def verify_callback(self, headers: dict[str, str], body: bytes) -> PaymentResult:
        if not settings.wechat_platform_cert or not settings.wechat_api_v3_key:
            raise PaymentVerifyError(
                "微信支付未配置：缺少 WECHAT_PLATFORM_CERT / WECHAT_API_V3_KEY，无法验签"
            )

        timestamp = headers.get("wechatpay-timestamp")
        nonce = headers.get("wechatpay-nonce")
        signature = headers.get("wechatpay-signature")
        if not (timestamp and nonce and signature):
            raise PaymentVerifyError("微信回调缺少 Wechatpay-* 验签头")

        self._check_timestamp(timestamp)

        body_text = body.decode("utf-8")
        # 验签明文串：timestamp\nnonce\nbody\n
        message = f"{timestamp}\n{nonce}\n{body_text}\n"
        if not _crypto.rsa_verify_sha256(
            settings.wechat_platform_cert, message, signature
        ):
            raise PaymentVerifyError("微信回调签名校验失败")

        try:
            event = json.loads(body_text)
            resource = event["resource"]
            plaintext = _crypto.aes_gcm_decrypt(
                api_v3_key=settings.wechat_api_v3_key,
                nonce=resource["nonce"],
                ciphertext_b64=resource["ciphertext"],
                associated_data=resource.get("associated_data"),
            )
            data = json.loads(plaintext.decode("utf-8"))
        except (KeyError, ValueError, UnicodeDecodeError) as exc:
            raise PaymentVerifyError(f"微信回调解密失败：{exc}") from exc
        except _crypto.CryptoError as exc:
            raise PaymentVerifyError(str(exc)) from exc

        trade_state = data.get("trade_state", "")
        success = trade_state == "SUCCESS"
        amount = data.get("amount") or {}
        amount_cents = amount.get("payer_total")
        if amount_cents is None:
            amount_cents = amount.get("total")
        return PaymentResult(
            success=success,
            provider_txn_id=str(data.get("transaction_id") or data.get("out_trade_no") or ""),
            amount_cents=amount_cents,
            currency=(amount.get("currency") or "CNY"),
            # out_trade_no 即本地订单号
            raw={"order_no": data.get("out_trade_no"), **data},
        )

    @staticmethod
    def _check_timestamp(timestamp: str) -> None:
        try:
            ts = int(timestamp)
        except (TypeError, ValueError) as exc:
            raise PaymentVerifyError("微信回调时间戳非法") from exc
        if abs(int(time.time()) - ts) > _TIMESTAMP_TOLERANCE_SECONDS:
            raise PaymentVerifyError("微信回调时间戳超出允许偏差，疑似重放")

    @staticmethod
    def _missing_create_credentials() -> list[str]:
        required = {
            "WECHAT_APP_ID": settings.wechat_app_id,
            "WECHAT_MCH_ID": settings.wechat_mch_id,
            "WECHAT_MCH_PRIVATE_KEY": settings.wechat_mch_private_key,
            "WECHAT_MCH_SERIAL_NO": settings.wechat_mch_serial_no,
            "WECHAT_API_V3_KEY": settings.wechat_api_v3_key,
            "WECHAT_NOTIFY_URL": settings.wechat_notify_url,
        }
        return [name for name, val in required.items() if not val]
