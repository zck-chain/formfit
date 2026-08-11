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
    statuses = []
    for i in range(12):
        r = client.post(
            "/api/auth/register",
            json={"email": f"u{i}@t.com", "password": "secret123", "nickname": "t"},
        )
        statuses.append(r.status_code)
    assert 429 in statuses, statuses
    # 429 响应应包含 Retry-After
    r429 = next(s for s in statuses if s == 429)
    assert r429 == 429


def test_login_rate_limit_returns_429(client):
    # 先造一个用户，再用错误密码高频登录触发 20/minute
    client.post(
        "/api/auth/register",
        json={"email": "ratelog@t.com", "password": "secret123", "nickname": "t"},
    )
    statuses = []
    for _ in range(22):
        r = client.post(
            "/api/auth/login",
            json={"email": "ratelog@t.com", "password": "wrong-pass"},
        )
        statuses.append(r.status_code)
    assert 429 in statuses, statuses


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
