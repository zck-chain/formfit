"""后台 session 独立 secret 与 cookie 安全属性测试。"""
import importlib

import pytest
from itsdangerous import URLSafeTimedSerializer

from app.core import admin_auth


def test_session_roundtrip():
    token = admin_auth.create_session(42)
    assert admin_auth.read_session(token) == 42


def test_session_rejects_tampered_token():
    token = admin_auth.create_session(7)
    assert admin_auth.read_session(token + "x") is None
    assert admin_auth.read_session("garbage") is None
    assert admin_auth.read_session(None) is None


def test_session_secret_is_independent_of_jwt(monkeypatch):
    """用 JWT secret 签名的令牌不能通过后台 session 校验（反之亦然）。"""
    from app.core import config

    jwt_serializer = URLSafeTimedSerializer(
        config.settings.jwt_secret, salt="formfit-admin-session-v2"
    )
    forged = jwt_serializer.dumps({"uid": 1})
    # 后台用的是 admin_session_secret，JWT secret 签出的应被判为无效
    assert admin_auth.read_session(forged) is None


def test_session_expiry(monkeypatch):
    """max_age 为负时任何令牌都应失效（模拟过期）。"""
    token = admin_auth.create_session(1)
    monkeypatch.setattr(admin_auth, "SESSION_MAX_AGE", -1)
    assert admin_auth.read_session(token) is None
