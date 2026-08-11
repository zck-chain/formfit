"""支付渠道共用的 RSA/AES 加解密辅助。

- 支付宝：商户私钥签名（RSA2 / SHA256withRSA）、支付宝公钥验签。
- 微信支付 V3：商户私钥签名请求、平台证书/公钥验签回调、APIv3 密钥 AES-256-GCM 解密。

凭证可能以"裸 base64"或完整 PEM 形式给出；这里统一规整后再加载，
证书（CERTIFICATE）自动提取其公钥。
"""
from __future__ import annotations

import base64

from cryptography import x509
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.types import (
    CertificatePublicKeyTypes,
    PrivateKeyTypes,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoError(Exception):
    """密钥/签名/解密本身非法（区别于验签不通过的伪造场景）。"""


def _wrap_pem(raw: str, label: str) -> str:
    raw = "".join(raw.split())
    body = "\n".join(raw[i : i + 64] for i in range(0, len(raw), 64))
    return f"-----BEGIN {label}-----\n{body}\n-----END {label}-----\n"


def _looks_like_pem(text: str) -> bool:
    return "BEGIN" in text


def load_private_key(pem: str) -> PrivateKeyTypes:
    """加载商户 RSA 私钥，兼容 PKCS#8（PRIVATE KEY）与 PKCS#1（RSA PRIVATE KEY），
    裸 base64 自动按 PKCS#8 包裹。"""
    text = pem.strip()
    candidates = [text] if _looks_like_pem(text) else [
        _wrap_pem(text, "PRIVATE KEY"),
        _wrap_pem(text, "RSA PRIVATE KEY"),
    ]
    last_exc: Exception | None = None
    for candidate in candidates:
        try:
            key = serialization.load_pem_private_key(candidate.encode("utf-8"), password=None)
            if key is not None:
                return key
        except ValueError as exc:  # 标签不匹配/格式错误，尝试下一种
            last_exc = exc
    raise CryptoError(f"私钥格式非法：{last_exc}")


def load_public_key(pem: str) -> CertificatePublicKeyTypes:
    """加载验签公钥，兼容 SPKI（PUBLIC KEY）、PKCS#1（RSA PUBLIC KEY）以及
    X.509 证书（CERTIFICATE，自动提取公钥）。"""
    text = pem.strip()
    if _looks_like_pem(text):
        candidates = [text]
    else:
        candidates = [
            _wrap_pem(text, "PUBLIC KEY"),
            _wrap_pem(text, "RSA PUBLIC KEY"),
            _wrap_pem(text, "CERTIFICATE"),
        ]

    last_exc: Exception | None = None
    for candidate in candidates:
        try:
            if "BEGIN CERTIFICATE" in candidate:
                cert = x509.load_pem_x509_certificate(candidate.encode("utf-8"))
                return cert.public_key()
            key = serialization.load_pem_public_key(candidate.encode("utf-8"))
            if key is not None:
                return key
        except ValueError as exc:
            last_exc = exc
    raise CryptoError(f"公钥/证书格式非法：{last_exc}")


def rsa_sign_sha256(private_key_pem: str, message: str) -> str:
    """用商户私钥对消息做 SHA256withRSA 签名，返回 base64。"""
    key = load_private_key(private_key_pem)
    signature = key.sign(message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("ascii")


def rsa_verify_sha256(public_key_pem: str, message: str, signature_b64: str) -> bool:
    """用公钥验签；返回 True/False（不抛异常），便于上层区分伪造。"""
    try:
        key = load_public_key(public_key_pem)
        key.verify(
            base64.b64decode(signature_b64),
            message.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def aes_gcm_decrypt(
    api_v3_key: str,
    nonce: str,
    ciphertext_b64: str,
    associated_data: str | None,
) -> bytes:
    """微信支付 V3 回调解密：AES-256-GCM，ciphertext 末 16 字节为 tag。

    APIv3 密钥必须为 32 字节；密钥错误/数据被篡改时抛 CryptoError。
    """
    key_bytes = api_v3_key.encode("utf-8")
    if len(key_bytes) != 32:
        raise CryptoError("微信 APIv3 密钥必须为 32 字节")
    try:
        data = base64.b64decode(ciphertext_b64)
    except (ValueError, TypeError) as exc:
        raise CryptoError("回调密文不是合法 base64") from exc
    if len(data) < 16:
        raise CryptoError("回调密文长度不足")
    aesgcm = AESGCM(key_bytes)
    aad = associated_data.encode("utf-8") if associated_data else None
    try:
        return aesgcm.decrypt(nonce.encode("utf-8"), data, aad)
    except (InvalidSignature, InvalidTag) as exc:  # AES-GCM 认证失败
        raise CryptoError("回调解密校验失败：密钥不匹配或数据被篡改") from exc
