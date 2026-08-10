"""pytest 公共夹具：每个测试用独立内存 SQLite，避免污染开发库 formfit.db。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.main import app
from app.models import *  # noqa: F401,F403  注册模型


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
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


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
