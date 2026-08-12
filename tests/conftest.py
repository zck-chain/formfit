"""pytest 公共夹具：每个测试用独立内存 SQLite，避免污染开发库 formfit.db。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.rate_limit import limiter
from app.db.session import Base, get_db
from app.main import app
from app.models import *  # noqa: F401,F403  注册模型


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """每个测试重置限流计数器，避免全局内存限流在测试间累积导致 429。"""
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def _enable_checkout_in_tests(monkeypatch):
    """测试默认开启下单（沙箱下单流程需要）。

    生产默认 CHECKOUT_ENABLED=false（kill switch）；测试套件需要验证完整沙箱下单链路，
    因此在测试环境默认打开。验证「关闭」路径的用例自行 monkeypatch
    app.api.routes.payment.settings.checkout_enabled = False。
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "checkout_enabled", True, raising=False)
    yield


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session):
    # /healthz 直接使用全局 engine 探活；测试期把它指向内存引擎，
    # 避免在工作树创建真实 formfit.db 文件。
    from app.core import health as health_module
    real_engine = health_module.engine
    health_module.engine = db_session.bind

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    health_module.engine = real_engine


@pytest.fixture()
def register_user(client):
    """注册一个用户并返回 (auth_headers, user_json)。"""

    def _register(email="user@test.com", password="secret123"):
        resp = client.post(
            "/api/auth/register",
            json={"email": email, "password": password, "nickname": "Tester"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        headers = {"Authorization": f"Bearer {data['access_token']}"}
        return headers, data["user"]

    return _register
