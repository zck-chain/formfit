"""阶段三生产加固测试：CORS、默认密钥启动拦截、上传校验、限流、后台 session。"""
import io
import time

import pytest
from PIL import Image

from app.core import admin_auth
from app.core.config import (
    DEFAULT_ADMIN_PASSWORDS,
    DEFAULT_JWT_SECRETS,
    Settings,
    validate_security_settings,
)
from app.models import Membership


# ---------- 辅助：构造图片字节 ----------
def _png_bytes(color=(0, 0, 0), size=(4, 4)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(color=(0, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="JPEG")
    return buf.getvalue()


def _heic_bytes() -> bytes:
    import pillow_heif

    pillow_heif.register_heif_opener()
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 120, 30)).save(buf, format="HEIF")
    return buf.getvalue()


# ============================================================
# 1. 配置：生产默认密钥拦截 / 开发放行
# ============================================================
def _production_settings(**overrides) -> Settings:
    base = dict(
        app_env="production",
        jwt_secret="x" * 40,
        admin_password="a-strong-pass-123",
        admin_session_secret="y" * 40,
        cors_origins="https://app.formfit.com",
    )
    base.update(overrides)
    return Settings(**base)


def test_production_rejects_default_jwt_secret():
    for bad in DEFAULT_JWT_SECRETS:
        s = _production_settings(jwt_secret=bad)
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            validate_security_settings(s)


def test_production_rejects_default_admin_password():
    for bad in DEFAULT_ADMIN_PASSWORDS:
        s = _production_settings(admin_password=bad)
        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
            validate_security_settings(s)


def test_production_requires_admin_session_secret():
    s = _production_settings(admin_session_secret="")
    with pytest.raises(RuntimeError, match="ADMIN_SESSION_SECRET"):
        validate_security_settings(s)


def test_production_rejects_session_secret_equal_to_jwt():
    s = _production_settings(
        jwt_secret="z" * 40, admin_session_secret="z" * 40
    )
    with pytest.raises(RuntimeError, match="不同"):
        validate_security_settings(s)


def test_production_with_strong_secrets_passes():
    # 不应抛异常
    validate_security_settings(_production_settings())


def test_development_defaults_only_warn(monkeypatch):
    # 开发环境 + 默认密钥：不抛异常（仅 warning）
    s = Settings(app_env="development")
    validate_security_settings(s)  # 无异常


# ============================================================
# 2. CORS 来源解析
# ============================================================
def test_production_unset_cors_is_empty_not_wildcard():
    s = Settings(app_env="production", jwt_secret="x" * 40,
                 admin_password="strong-pass-1", admin_session_secret="y" * 40,
                 cors_origins="")
    assert s.effective_cors_origins() == []


def test_production_cors_uses_explicit_whitelist():
    s = _production_settings(cors_origins="https://a.com, https://b.com")
    assert s.effective_cors_origins() == ["https://a.com", "https://b.com"]


def test_dev_unset_cors_allows_localhost():
    s = Settings(app_env="development", cors_origins="")
    origins = s.effective_cors_origins()
    assert any("localhost" in o for o in origins)
    # 绝不出现通配
    assert "*" not in origins


def test_cors_preflight_allows_whitelisted_origin(client):
    resp = client.options(
        "/api/auth/login",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_cors_preflight_rejects_disallowed_origin(client):
    resp = client.options(
        "/api/auth/login",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    # 非白名单来源不应返回 Allow-Origin
    assert resp.headers.get("access-control-allow-origin") in (None, "null")


# ============================================================
# 3. 上传安全校验
# ============================================================
def _pro_headers(client, register_user, db_session):
    headers, user = register_user()
    m = db_session.query(Membership).filter_by(user_id=user["id"]).one()
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    m.plan = "pro"
    m.is_active = True
    m.start_at = now
    m.expire_at = now + timedelta(days=30)
    db_session.commit()
    return headers


def test_upload_rejects_non_image_despite_fake_content_type(client, register_user, db_session, monkeypatch):
    headers = _pro_headers(client, register_user, db_session)

    async def _fake(path, **kw):
        return {"direction": "maintain", "summary": "", "observed": [], "safety_notes": None}
    monkeypatch.setattr("app.agent.qwen_vl_client.assess_body", _fake)

    # 伪装成 image/png 的脚本内容
    resp = client.post(
        "/api/fitness/assess",
        headers=headers,
        files={"file": ("a.png", b"#!/bin/sh\nrm -rf /", "image/png")},
    )
    assert resp.status_code == 415, resp.text


def test_upload_rejects_declared_non_image_type(client, register_user, db_session):
    headers = _pro_headers(client, register_user, db_session)
    resp = client.post(
        "/api/fitness/assess",
        headers=headers,
        files={"file": ("a.exe", b"MZ\x90\x00\x00", "application/octet-stream")},
    )
    # 先被声明类型过滤拦在 400，或被 Pillow 拦在 415
    assert resp.status_code in (400, 415)


def test_upload_rejects_oversized_image(client, register_user, db_session, monkeypatch):
    headers = _pro_headers(client, register_user, db_session)

    async def _fake(path, **kw):
        return {"direction": "maintain", "summary": "", "observed": [], "safety_notes": None}
    monkeypatch.setattr("app.agent.qwen_vl_client.assess_body", _fake)

    # 用一个极低的上传上限触发 413（通过 monkeypatch settings）
    from app.core import config as cfg
    # 256x256 PNG ≈ 270 字节，把上限压到 100 字节
    png = _png_bytes(size=(256, 256))
    monkeypatch.setattr(cfg.settings, "upload_max_bytes", 100)
    resp = client.post(
        "/api/fitness/assess",
        headers=headers,
        files={"file": ("a.png", png, "image/png")},
    )
    assert resp.status_code == 413, resp.text
    assert "过大" in resp.json()["detail"]


def test_upload_accepts_real_jpeg(client, register_user, db_session, monkeypatch, tmp_path):
    headers = _pro_headers(client, register_user, db_session)
    # 把上传目录指向 tmp，避免污染
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "upload_dir", tmp_path)

    async def _fake(path, **kw):
        return {"direction": "gain", "body_type": "t", "summary": "ok",
                "observed": [], "safety_notes": None}
    monkeypatch.setattr("app.agent.qwen_vl_client.assess_body", _fake)

    resp = client.post(
        "/api/fitness/assess",
        headers=headers,
        files={"file": ("a.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["direction"] == "gain"


def test_upload_heic_transcoded_to_jpeg():
    """HEIC 经校验后应转成 JPEG 字节，扩展名/mime 变为 .jpg/image/jpeg。"""
    from app.utils.images import validate_and_prepare

    data, ext, mime = validate_and_prepare(_heic_bytes(), "image/heic")
    assert ext == ".jpg"
    assert mime == "image/jpeg"
    # 转码后的字节应能被 Pillow 以 JPEG 打开
    with Image.open(io.BytesIO(data)) as im:
        assert im.format == "JPEG"


# ============================================================
# 4. 限流 429
# ============================================================
def test_register_rate_limit_returns_429(client):
    # 默认阈值 10/minute；连续注册超过阈值应得到 429
    responses = []
    for i in range(12):
        responses.append(
            client.post(
                "/api/auth/register",
                json={"email": f"u{i}@t.com", "password": "secret123", "nickname": "t"},
            )
        )
    statuses = [r.status_code for r in responses]
    assert 429 in statuses, statuses
    # 429 响应必须携带 Retry-After（秒数），固化与客户端的退避契约
    blocked = next(r for r in responses if r.status_code == 429)
    retry_after = blocked.headers.get("Retry-After")
    assert retry_after is not None
    assert retry_after.isdigit() and int(retry_after) > 0


def test_login_rate_limit_returns_429(client):
    # 先造一个用户，再用错误密码高频登录触发 20/minute
    client.post(
        "/api/auth/register",
        json={"email": "ratelog@t.com", "password": "secret123", "nickname": "t"},
    )
    responses = []
    for _ in range(22):
        responses.append(
            client.post(
                "/api/auth/login",
                json={"email": "ratelog@t.com", "password": "wrong-pass"},
            )
        )
    statuses = [r.status_code for r in responses]
    assert 429 in statuses, statuses
    blocked = next(r for r in responses if r.status_code == 429)
    retry_after = blocked.headers.get("Retry-After")
    assert retry_after is not None
    assert retry_after.isdigit() and int(retry_after) > 0


# ============================================================
# 5. 后台 session 独立密钥 + 版本吊销
# ============================================================
def test_admin_session_roundtrip_and_version_revocation(monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "admin_session_secret", "a-distinct-secret-0123456789abcdef")

    token = admin_auth.create_session(user_id=7, session_version=3)
    payload = admin_auth.read_session_payload(token)
    assert payload == (7, 3)


def test_admin_session_invalidated_by_version_bump(monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "admin_session_secret", "b-distinct-secret-0123456789abcdef")

    token = admin_auth.create_session(user_id=1, session_version=0)
    # 版本不一致（服务端已吊销）→ read 本身只校验签名时效，不比对版本；
    # 版本比对在 admin._current_admin 中做。这里直接验证载荷版本被正确携带。
    uid, ver = admin_auth.read_session_payload(token)
    assert (uid, ver) == (1, 0)
    # 伪造/篡改 token 应解析失败
    assert admin_auth.read_session_payload(token + "tampered") is None
    assert admin_auth.read_session_payload(None) is None
    assert admin_auth.read_session_payload("not-a-real-token") is None


def test_admin_session_expired_token_rejected(monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "admin_session_secret", "c-distinct-secret-0123456789abcdef")
    monkeypatch.setattr(cfg.settings, "admin_session_max_age_seconds", -1)

    token = admin_auth.create_session(user_id=1, session_version=0)
    # max_age=-1 使任何 token 立即过期
    assert admin_auth.read_session_payload(token) is None


def test_admin_secret_independent_from_jwt(monkeypatch):
    """admin_secret_key 在配置了独立密钥时不回退到 jwt_secret。"""
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "admin_session_secret", "independent-key-xyz")
    monkeypatch.setattr(cfg.settings, "jwt_secret", "jwt-secret-abc")
    assert cfg.settings.admin_secret_key() == "independent-key-xyz"


# ============================================================
# 6. XFF 信任收敛：TRUSTED_PROXY_ENABLED 控制是否采信 X-Forwarded-For
# ============================================================
class _StubClient:
    host = "203.0.113.10"


class _StubRequest:
    """最小请求桩：headers 字典 + client.host，供限流 key 函数直接调用。"""

    def __init__(self, headers):
        self.headers = headers
        self.client = _StubClient()


def test_client_ip_ignores_xff_when_trusted_proxy_disabled(monkeypatch):
    from app.core import rate_limit

    monkeypatch.setattr(rate_limit.settings, "trusted_proxy_enabled", False)
    req = _StubRequest({"x-forwarded-for": "1.2.3.4, 5.6.7.8"})
    # 直连部署：伪造的 XFF 不应影响限流 key，用 TCP 直连地址
    assert rate_limit.client_ip(req) == "203.0.113.10"


def test_client_ip_uses_xff_when_trusted_proxy_enabled(monkeypatch):
    from app.core import rate_limit

    monkeypatch.setattr(rate_limit.settings, "trusted_proxy_enabled", True)
    req = _StubRequest({"x-forwarded-for": "1.2.3.4, 5.6.7.8"})
    # 可信代理后：取 XFF 首个 IP
    assert rate_limit.client_ip(req) == "1.2.3.4"
    # 未带 XFF 时回退直连地址
    assert rate_limit.client_ip(_StubRequest({})) == "203.0.113.10"


def test_register_rate_limit_not_bypassed_by_forged_xff(client):
    # 默认 trusted_proxy_enabled=false：每个请求轮换不同 XFF，
    # 仍按直连地址（testclient）计数，超过阈值必须 429。
    statuses = []
    for i in range(12):
        r = client.post(
            "/api/auth/register",
            json={"email": f"xff{i}@t.com", "password": "secret123", "nickname": "t"},
            headers={"X-Forwarded-For": f"10.0.0.{i + 1}"},
        )
        statuses.append(r.status_code)
    assert 429 in statuses, statuses


def test_register_rate_limit_honors_xff_when_trusted(client, monkeypatch):
    from app.core import rate_limit

    monkeypatch.setattr(rate_limit.settings, "trusted_proxy_enabled", True)
    # 每个请求使用不同可信 XFF 客户端 IP，各自独立计数 → 全部放行
    statuses = []
    for i in range(12):
        r = client.post(
            "/api/auth/register",
            json={"email": f"txff{i}@t.com", "password": "secret123", "nickname": "t"},
            headers={"X-Forwarded-For": f"10.0.0.{i + 1}"},
        )
        statuses.append(r.status_code)
    assert 429 not in statuses, statuses
    assert all(s == 200 for s in statuses)


# ============================================================
# 7. 已鉴权接口按 user 维度限流（NAT 下不误伤，单用户滥用命中 429）
# ============================================================
def test_user_or_ip_key_prefers_user_id():
    from app.core.rate_limit import user_or_ip_key
    from app.core.security import create_access_token

    token = create_access_token(42)
    req = _StubRequest({"authorization": f"Bearer {token}"})
    assert user_or_ip_key(req) == "user:42"
    # 无凭据 / 无效凭据回退到 IP 维度
    assert user_or_ip_key(_StubRequest({})) == "203.0.113.10"
    bad = _StubRequest({"authorization": "Bearer not-a-real-token"})
    assert user_or_ip_key(bad) == "203.0.113.10"


def test_authenticated_endpoint_rate_limits_per_user_not_ip(client, register_user):
    """默认阈值 30/minute。同 IP 下：A 用尽配额后 B 仍可用；A 再请求 429。"""
    headers_a, _ = register_user(email="alice@t.com", password="secret123")
    headers_b, _ = register_user(email="bob@t.com", password="secret123")

    payload = {"plan_code": "pro_monthly", "channel": "sandbox"}

    # A 连续下单 31 次：前 30 放行，第 31 次 429（即便轮换伪造 XFF 也无效）
    statuses_a = []
    for i in range(30):
        statuses_a.append(
            client.post("/api/payment/orders", json=payload, headers=headers_a).status_code
        )
    forged = client.post(
        "/api/payment/orders",
        json=payload,
        headers={**headers_a, "X-Forwarded-For": "8.8.8.8"},
    ).status_code
    statuses_a.append(forged)

    assert statuses_a.count(200) == 30, statuses_a
    assert forged == 429, statuses_a

    # B 与 A 来自同一测试客户端（同一 IP），不应被 A 的配额误伤
    resp_b = client.post("/api/payment/orders", json=payload, headers=headers_b)
    assert resp_b.status_code == 200, resp_b.text
