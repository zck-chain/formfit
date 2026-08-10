"""端到端集成测试：后台登录 cookie 安全 + 体态评估上传入口。

使用内存 SQLite 覆盖 get_db，不触碰真实 formfit.db；
评估链路的 AI 调用被 mock，避免外部网络依赖。
"""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes
from app.core import config
from app.db.session import Base, get_db
from app.main import app
from app.models import Membership, User


@pytest.fixture()
def client(monkeypatch):
    # 内存数据库：StaticPool 保证所有连接共享同一个内存库
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # 建一个管理员
    from app.core.security import hash_password

    db = TestingSession()
    admin = User(
        email="admin@test.local",
        hashed_password=hash_password("correct-horse-123"),
        nickname="admin",
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.flush()
    db.add(Membership(user_id=admin.id, plan="pro", is_active=True))

    # 建一个普通用户
    from app.core.security import create_access_token

    user = User(
        email="user@test.local",
        hashed_password=hash_password("whatever-123456"),
        nickname="u",
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    user_token = create_access_token(user.id)
    db.close()

    def _override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app), user_token
    app.dependency_overrides.clear()


def _png_bytes(mode="RGB", size=(8, 8)):
    buf = io.BytesIO()
    Image.new(mode, size, (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


# ---------- 后台登录 cookie ----------
def test_admin_login_cookie_not_secure_in_dev(client, monkeypatch):
    monkeypatch.setattr(config.settings, "environment", "development", raising=False)
    c, _ = client
    resp = c.post(
        "/admin/login",
        data={"email": "admin@test.local", "password": "correct-horse-123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    set_cookie = resp.headers["set-cookie"]
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()
    # 开发（HTTP）不强制 secure
    assert "secure" not in set_cookie.lower()


def test_admin_login_cookie_secure_in_production(client, monkeypatch):
    monkeypatch.setattr(config.settings, "environment", "production", raising=False)
    c, _ = client
    resp = c.post(
        "/admin/login",
        data={"email": "admin@test.local", "password": "correct-horse-123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "secure" in resp.headers["set-cookie"].lower()


def test_admin_login_wrong_password(client):
    c, _ = client
    resp = c.post(
        "/admin/login",
        data={"email": "admin@test.local", "password": "wrong"},
        follow_redirects=False,
    )
    assert resp.status_code == 401


# ---------- 体态评估上传 ----------
def _mock_assess(save_path, **kwargs):
    import asyncio

    async def _fake(*a, **k):
        return {
            "direction": "maintain",
            "body_type": "test",
            "summary": "ok",
            "observed": [],
            "safety_notes": "x",
        }

    return _fake()


def test_assess_rejects_non_image(client, monkeypatch):
    monkeypatch.setattr(
        routes.fitness.qwen_vl_client, "assess_body", _mock_assess
    )
    c, token = client
    resp = c.post(
        "/api/fitness/assess",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("evil.jpg", b"<?php echo 1; ?>", "image/jpeg")},
    )
    assert resp.status_code == 400


def test_assess_rejects_disallowed_content_type(client, monkeypatch):
    monkeypatch.setattr(
        routes.fitness.qwen_vl_client, "assess_body", _mock_assess
    )
    c, token = client
    resp = c.post(
        "/api/fitness/assess",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("x.gif", _png_bytes(), "image/gif")},
    )
    assert resp.status_code == 400


def test_assess_oversized_content_length_rejected_early(client, monkeypatch):
    """Content-Length 超过上限时，中间件直接 413，不读取 body。"""
    c, token = client
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Length": str(config.settings.upload_max_bytes + 100),
        "Content-Type": "multipart/form-data; boundary=----x",
    }
    resp = c.post("/api/fitness/assess", headers=headers, content=b"------x--")
    assert resp.status_code == 413


def test_assess_accepts_valid_image(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        routes.fitness.qwen_vl_client, "assess_body", _mock_assess
    )
    # 上传目录指向临时目录，避免污染
    monkeypatch.setattr(config.settings, "upload_dir", tmp_path)
    c, token = client
    resp = c.post(
        "/api/fitness/assess",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("photo.png", _png_bytes(mode="RGBA"), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["direction"] == "maintain"
    # 合法图片确实落盘
    saved = list(tmp_path.glob("*"))
    assert len(saved) == 1


def test_assess_requires_auth(client):
    c, _ = client
    resp = c.post(
        "/api/fitness/assess",
        files={"file": ("x.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 401
