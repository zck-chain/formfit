"""支付宝 / 微信支付渠道测试：注册、缺凭证报错、回调验签成功与伪造失败、核销幂等复用。

无真实凭证：用本地生成的 RSA 密钥对/自签证书模拟"商户私钥 + 渠道公钥/证书"，
确保验签逻辑正确；拿到真实凭证后填 .env 即可联调，无需改代码。
"""
import base64
import datetime
import json
import urllib.parse

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from app.core.config import settings
from app.payment import registry
from app.payment._crypto import aes_gcm_decrypt, rsa_sign_sha256, rsa_verify_sha256
from app.payment.base import PaymentVerifyError
from app.payment.alipay import AlipayProvider, _build_sign_string
from app.payment.wechat import WechatProvider


def _corrupt_signature(sig: str) -> str:
    """确定性破坏一个 base64 签名：把首字符换成另一个有效 base64 字符。

    不能用 ``sig.replace("A", "B")`` —— 当随机生成的 344 字符签名恰好不含 "A"
    时（约 0.5% 概率），replace 是空操作，伪造用例会偶发“验签通过”而误报失败。
    RSA-PKCS1v15 对任何比特翻转都几乎必然验签失败，故改首字符即可稳定触发拒绝。
    """
    first = sig[0]
    replacement = "B" if first == "A" else "A"
    return replacement + sig[1:]


# ---------- 测试密钥夹具 ----------
@pytest.fixture()
def rsa_keypair():
    """生成一对 RSA 私钥/公钥（PEM，PKCS#8）。"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv_pem, pub_pem, key


@pytest.fixture()
def self_signed_cert(rsa_keypair):
    """生成自签 X.509 证书（模拟微信支付平台证书），返回 (cert_pem, cert_private_key)。"""
    priv_pem, _, key = rsa_keypair
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "wechatpay-test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return cert_pem, key


@pytest.fixture(autouse=True)
def _clear_registry_cache():
    registry._enabled.cache_clear()
    yield
    registry._enabled.cache_clear()


class _FakeOrder:
    def __init__(self, order_no="FF202608110001", amount_cents=2800, currency="CNY",
                 plan_code="pro_monthly", duration_days=30):
        self.order_no = order_no
        self.amount_cents = amount_cents
        self.currency = currency
        self.plan_code = plan_code
        self.duration_days = duration_days


# ---------- 注册 ----------
def test_alipay_and_wechat_registered():
    assert "alipay" in registry._PROVIDER_FACTORIES
    assert "wechat" in registry._PROVIDER_FACTORIES
    assert registry._PROVIDER_FACTORIES["alipay"] is AlipayProvider
    assert registry._PROVIDER_FACTORIES["wechat"] is WechatProvider


def test_channels_enable_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "payment_channels", "sandbox,alipay,wechat")
    registry._enabled.cache_clear()
    assert registry.supported_channels() == ["sandbox", "alipay", "wechat"]
    assert registry.provider_exists("alipay")
    assert registry.provider_exists("wechat")


# ---------- 支付宝 ----------
def test_alipay_missing_credentials_raises(monkeypatch):
    for field in (
        "alipay_app_id", "alipay_private_key", "alipay_public_key", "alipay_callback_url"
    ):
        monkeypatch.setattr(settings, field, "")
    prov = AlipayProvider()
    with pytest.raises(PaymentVerifyError) as exc:
        prov.create_payment(_FakeOrder())
    assert "未配置" in str(exc.value)


def test_alipay_create_payment_returns_signed_order_str(monkeypatch, rsa_keypair):
    priv, pub, _ = rsa_keypair
    monkeypatch.setattr(settings, "alipay_app_id", "2026000000000000")
    monkeypatch.setattr(settings, "alipay_private_key", priv)
    monkeypatch.setattr(settings, "alipay_public_key", pub)
    monkeypatch.setattr(settings, "alipay_callback_url", "https://api.formfit.com/cb/alipay")

    cred = AlipayProvider().create_payment(_FakeOrder())
    assert cred["provider"] == "alipay"
    assert cred["order_no"] == "FF202608110001"
    # orderStr 可被解析回参数，且能用"支付宝公钥"验签（测试中即同一密钥对的公钥）
    qs = urllib.parse.parse_qs(cred["order_str"])
    sign = qs["sign"][0]
    params = {k: v[0] for k, v in qs.items() if k != "sign"}
    assert rsa_verify_sha256(pub, _build_sign_string(params), sign) is True
    # 金额以元为单位、out_trade_no 透传
    biz = json.loads(params["biz_content"])
    assert biz["out_trade_no"] == "FF202608110001"
    assert biz["total_amount"] == "28.00"


def _alipay_callback_body(priv_key: str, overrides: dict | None = None,
                          tamper_sign: bool = False) -> bytes:
    data = {
        "out_trade_no": "FF202608110001",
        "trade_no": "2026081100001",
        "trade_status": "TRADE_SUCCESS",
        "total_amount": "28.00",
        "currency": "CNY",
        "app_id": "2026000000000000",
        "sign_type": "RSA2",
    }
    if overrides:
        data.update(overrides)
    # 支付宝异步通知的签名串不含 sign 与 sign_type
    sign_data = {k: v for k, v in data.items() if k != "sign_type"}
    data["sign"] = rsa_sign_sha256(priv_key, _build_sign_string(sign_data))
    if tamper_sign:
        data["sign"] = _corrupt_signature(data["sign"])
    return urllib.parse.urlencode(data).encode("utf-8")


def test_alipay_verify_callback_success(monkeypatch, rsa_keypair):
    priv, pub, _ = rsa_keypair
    monkeypatch.setattr(settings, "alipay_public_key", pub)
    body = _alipay_callback_body(priv)
    result = AlipayProvider().verify_callback({}, body)
    assert result.success is True
    assert result.provider_txn_id == "2026081100001"
    assert result.amount_cents == 2800
    assert result.raw["order_no"] == "FF202608110001"


def test_alipay_forged_signature_rejected(monkeypatch, rsa_keypair):
    priv, pub, _ = rsa_keypair
    monkeypatch.setattr(settings, "alipay_public_key", pub)
    body = _alipay_callback_body(priv, tamper_sign=True)
    with pytest.raises(PaymentVerifyError, match="签名校验失败"):
        AlipayProvider().verify_callback({}, body)


def test_alipay_tampered_amount_rejected(monkeypatch, rsa_keypair):
    """签名是对原始 body 计算的，篡改金额后验签应失败。"""
    priv, pub, _ = rsa_keypair
    monkeypatch.setattr(settings, "alipay_public_key", pub)
    # 用合法金额签名，再把金额改小但保留旧签名
    body = _alipay_callback_body(priv, overrides={"total_amount": "28.00"})
    tampered = body.replace(b"total_amount=28.00", b"total_amount=0.01")
    with pytest.raises(PaymentVerifyError):
        AlipayProvider().verify_callback({}, tampered)


def test_alipay_missing_public_key_rejects_callback(monkeypatch):
    monkeypatch.setattr(settings, "alipay_public_key", "")
    with pytest.raises(PaymentVerifyError, match="ALIPAY_PUBLIC_KEY"):
        AlipayProvider().verify_callback({}, b"")


def test_alipay_trade_finished_is_success(monkeypatch, rsa_keypair):
    priv, pub, _ = rsa_keypair
    monkeypatch.setattr(settings, "alipay_public_key", pub)
    body = _alipay_callback_body(priv, {"trade_status": "TRADE_FINISHED"})
    assert AlipayProvider().verify_callback({}, body).success is True


# ---------- 微信 ----------
def test_wechat_missing_credentials_raises(monkeypatch):
    for field in (
        "wechat_app_id", "wechat_mch_id", "wechat_api_v3_key",
        "wechat_mch_private_key", "wechat_mch_serial_no", "wechat_notify_url",
    ):
        monkeypatch.setattr(settings, field, "")
    with pytest.raises(PaymentVerifyError) as exc:
        WechatProvider().create_payment(_FakeOrder())
    assert "未配置" in str(exc.value)


class _FakeHttpxResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _RecordingClient:
    """记录请求并用固定响应返回的假 httpx.Client，用于校验下单签名与载荷。"""

    def __init__(self, response_payload):
        self.response = _FakeHttpxResponse(response_payload)
        self.calls = []

    def post(self, url, content=None, headers=None):
        self.calls.append({"url": url, "content": content, "headers": headers})
        return self.response

    def close(self):
        pass


def test_wechat_create_payment_signs_request_and_returns_app_params(
    monkeypatch, rsa_keypair
):
    priv, pub, _ = rsa_keypair
    monkeypatch.setattr(settings, "wechat_app_id", "wxappid123")
    monkeypatch.setattr(settings, "wechat_mch_id", "1900000001")
    monkeypatch.setattr(settings, "wechat_api_v3_key", "x" * 32)
    monkeypatch.setattr(settings, "wechat_mch_private_key", priv)
    monkeypatch.setattr(settings, "wechat_mch_serial_no", "SERIAL123")
    monkeypatch.setattr(settings, "wechat_notify_url", "https://api.formfit.com/cb/wechat")

    recorder = _RecordingClient({"prepay_id": "wx-prepay-xyz"})
    cred = WechatProvider(client=recorder).create_payment(_FakeOrder())

    # 向微信 V3 下单接口发了请求，带 Authorization 签名
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["url"].endswith("/v3/pay/transactions/app")
    assert call["headers"]["Authorization"].startswith("WECHATPAY2-SHA256-RSA2048 ")
    assert 'mchid="1900000001"' in call["headers"]["Authorization"]
    assert 'serial_no="SERIAL123"' in call["headers"]["Authorization"]

    payload = json.loads(call["content"])
    assert payload["out_trade_no"] == "FF202608110001"
    assert payload["amount"]["total"] == 2800

    # 返回给客户端的 APP 支付参数用商户私钥二次签名，可用对应公钥验证
    assert cred["prepayid"] == "wx-prepay-xyz"
    assert cred["partnerid"] == "1900000001"
    assert cred["package"] == "Sign=WXPay"
    sign_msg = (
        f"{cred['appid']}\n{cred['timestamp']}\n{cred['noncestr']}\n{cred['prepayid']}\n"
    )
    assert rsa_verify_sha256(pub, sign_msg, cred["sign"]) is True


def _wechat_callback(platform_key, api_v3_key: str, resource_plain: dict,
                     tamper_sign: bool = False, bad_timestamp: bool = False):
    """构造一次微信 V3 支付成功回调：用平台证书私钥签外层，用 APIV3 密钥加密 resource。"""
    import secrets as _s
    import time as _t

    nonce = _s.token_urlsafe(12)
    associated = "transaction"
    plaintext = json.dumps(resource_plain, separators=(",", ":")).encode()
    # AES-256-GCM 加密：cryptography AESGCM 输出 ciphertext||tag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ct = AESGCM(api_v3_key.encode()).encrypt(nonce.encode(), plaintext, associated.encode())
    resource = {
        "nonce": nonce,
        "ciphertext": base64.b64encode(ct).decode(),
        "associated_data": associated,
        "algorithm": "AEAD_AES_256_GCM",
    }
    body = json.dumps(
        {"id": "evt-1", "event_type": "TRANSACTION.SUCCESS", "resource": resource},
        separators=(",", ":"),
    )
    timestamp = str(int(_t.time()) - 3600 if bad_timestamp else int(_t.time()))
    sign_msg = f"{timestamp}\n{nonce}\n{body}\n"
    signature = rsa_sign_sha256(platform_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode(), sign_msg)
    if tamper_sign:
        signature = _corrupt_signature(signature)
    headers = {
        "wechatpay-timestamp": timestamp,
        "wechatpay-nonce": nonce,
        "wechatpay-signature": signature,
    }
    return headers, body.encode()


def test_wechat_verify_callback_success(monkeypatch, self_signed_cert):
    cert_pem, cert_key = self_signed_cert
    api_v3_key = "0123456789abcdef0123456789abcdef"  # 32 字节
    monkeypatch.setattr(settings, "wechat_platform_cert", cert_pem)
    monkeypatch.setattr(settings, "wechat_api_v3_key", api_v3_key)

    headers, body = _wechat_callback(
        cert_key, api_v3_key,
        {
            "out_trade_no": "FF202608110001",
            "transaction_id": "4200000000202608110000000001",
            "trade_state": "SUCCESS",
            "amount": {"payer_total": 2800, "total": 2800, "currency": "CNY"},
        },
    )
    result = WechatProvider().verify_callback(headers, body)
    assert result.success is True
    assert result.provider_txn_id == "4200000000202608110000000001"
    assert result.amount_cents == 2800
    assert result.raw["order_no"] == "FF202608110001"


def test_wechat_forged_signature_rejected(monkeypatch, self_signed_cert):
    cert_pem, cert_key = self_signed_cert
    api_v3_key = "0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(settings, "wechat_platform_cert", cert_pem)
    monkeypatch.setattr(settings, "wechat_api_v3_key", api_v3_key)

    headers, body = _wechat_callback(
        cert_key, api_v3_key, {"out_trade_no": "X", "trade_state": "SUCCESS"},
        tamper_sign=True,
    )
    with pytest.raises(PaymentVerifyError, match="签名校验失败"):
        WechatProvider().verify_callback(headers, body)


def test_wechat_wrong_api_key_decrypt_fails(monkeypatch, self_signed_cert):
    cert_pem, cert_key = self_signed_cert
    good_key = "0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(settings, "wechat_platform_cert", cert_pem)
    monkeypatch.setattr(settings, "wechat_api_v3_key", good_key)
    # 用正确 key 加密，但验签/解密时换成另一个 32 字节 key
    headers, body = _wechat_callback(
        cert_key, good_key, {"out_trade_no": "X", "trade_state": "SUCCESS"}
    )
    monkeypatch.setattr(settings, "wechat_api_v3_key", "ffffffffffffffffffffffffffffffff")
    with pytest.raises(PaymentVerifyError, match="解密"):
        WechatProvider().verify_callback(headers, body)


def test_wechat_stale_timestamp_rejected(monkeypatch, self_signed_cert):
    cert_pem, cert_key = self_signed_cert
    api_v3_key = "0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(settings, "wechat_platform_cert", cert_pem)
    monkeypatch.setattr(settings, "wechat_api_v3_key", api_v3_key)
    headers, body = _wechat_callback(
        cert_key, api_v3_key, {"trade_state": "SUCCESS"}, bad_timestamp=True
    )
    with pytest.raises(PaymentVerifyError, match="时间戳|重放"):
        WechatProvider().verify_callback(headers, body)


def test_wechat_missing_credentials_reject_callback(monkeypatch):
    monkeypatch.setattr(settings, "wechat_platform_cert", "")
    monkeypatch.setattr(settings, "wechat_api_v3_key", "")
    with pytest.raises(PaymentVerifyError, match="未配置"):
        WechatProvider().verify_callback({}, b"{}")


# ---------- 核销幂等复用 payment_service（支付宝回调走通核销）----------
def test_alipay_callback_fulfills_order_idempotently(
    client, register_user, db_session, monkeypatch, rsa_keypair
):
    """端到端：支付宝验签通过后复用 payment_service 核销，重复回调幂等。"""
    priv, pub, _ = rsa_keypair
    monkeypatch.setattr(settings, "payment_channels", "sandbox,alipay")
    monkeypatch.setattr(settings, "alipay_public_key", pub)
    monkeypatch.setattr(settings, "alipay_app_id", "2026000000000000")
    registry._enabled.cache_clear()

    from app.models import Membership, Order

    headers, user = register_user()
    # 直接建一笔 alipay 订单（绕开 create_payment，避免缺商户私钥）
    order = Order(
        order_no="FF202608110001", user_id=user["id"], plan="pro", plan_code="pro_monthly",
        duration_days=30, amount_cents=2800, currency="CNY",
        payment_channel="alipay", status="pending",
    )
    db_session.add(order)
    db_session.commit()

    body = _alipay_callback_body(priv)
    resp = client.post("/api/payment/callback/alipay", content=body, headers={})
    assert resp.status_code == 200, resp.text
    # 支付宝成功应答为纯文本 success
    assert resp.text == "success"

    db_session.expire_all()
    m = db_session.query(Membership).filter_by(user_id=user["id"]).one()
    assert m.is_active is True and m.plan == "pro"
    db_order = db_session.query(Order).filter_by(order_no="FF202608110001").one()
    assert db_order.status == "fulfilled"

    # 重放同一回调：幂等，不再叠加时长
    expire1 = m.expire_at
    resp2 = client.post("/api/payment/callback/alipay", content=body, headers={})
    assert resp2.status_code == 200
    db_session.expire_all()
    m2 = db_session.query(Membership).filter_by(user_id=user["id"]).one()
    assert m2.expire_at == expire1
