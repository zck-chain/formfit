"""N1 生产部署基线测试：/healthz、生产部署校验、结构化日志、敏感信息脱敏。"""
from __future__ import annotations

import io
import json
import logging
import os

import pytest
from fastapi.testclient import TestClient

from app.core.config import (
    Settings,
    validate_deployment_settings,
    validate_security_settings,
)
from app.core import health as health_module
from app.core.logging_config import _JsonFormatter, configure_logging, sanitize_headers


# ---------- 辅助：构造合规生产配置 ----------
def _prod(**overrides) -> Settings:
    base = dict(
        app_env="production",
        jwt_secret="x" * 40,
        admin_password="a-strong-pass-123",
        admin_session_secret="y" * 40,
        cors_origins="https://app.formfit.com",
        database_url="sqlite:////data/formfit.db",
        payment_channels="",
    )
    base.update(overrides)
    return Settings(**base)


# ============================================================
# 1. /healthz：健康 / 异常路径 + 无敏感信息
# ============================================================
def test_healthz_ok_when_database_reachable(client, monkeypatch):
    # conftest 的内存库可正常查询
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok"}
    # 响应不得包含路径、连接串或密钥
    text = resp.text.lower()
    assert "formfit.db" not in text
    assert "sqlite" not in text
    assert "secret" not in text
    assert "password" not in text


def test_healthz_returns_503_when_database_unavailable(client, monkeypatch):
    def _boom():
        import sqlalchemy
        raise sqlalchemy.exc.SQLAlchemyError("engine=postgres://user:supersecret@db/prod")

    # check_database 内部调用 engine.connect；用抛错桩替换
    monkeypatch.setattr(health_module, "engine", type("E", (), {"connect": staticmethod(_boom)})())

    resp = client.get("/healthz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "error"
    # 错误原因必须笼统，绝不回传底层连接串/密码
    assert body["reason"] == "database unavailable"
    assert "supersecret" not in resp.text
    assert "postgres://" not in resp.text


def test_healthz_bypasses_access_log(client, caplog):
    # /healthz 不应产生 http_request 访问日志（避免噪音），但应带 X-Request-ID
    with caplog.at_level(logging.INFO, logger="formfit"):
        resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.headers.get("x-request-id")
    events = [r for r in caplog.records if getattr(r, "event", None) == "http_request"]
    assert events == []


def test_request_id_echoed_and_generated(client):
    # 透传上游 X-Request-ID
    resp = client.get("/healthz", headers={"X-Request-ID": "trace-abc-123"})
    assert resp.headers["x-request-id"] == "trace-abc-123"


# ============================================================
# 2. 生产部署校验：单 worker / 禁内存库 / 禁沙箱
# ============================================================
def test_production_sqlite_rejects_multiple_workers(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    s = _prod()
    with pytest.raises(RuntimeError, match="单 worker"):
        validate_deployment_settings(s)


def test_production_sqlite_accepts_single_worker(monkeypatch):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    validate_deployment_settings(_prod())  # 不抛


def test_production_rejects_in_memory_database(monkeypatch):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    s = _prod(database_url="sqlite:///:memory:")
    with pytest.raises(RuntimeError, match="内存库"):
        validate_deployment_settings(s)


def test_production_rejects_sandbox_payment_channel(monkeypatch):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    s = _prod(payment_channels="sandbox")
    with pytest.raises(RuntimeError, match="sandbox"):
        validate_deployment_settings(s)


def test_production_allows_real_channels_only(monkeypatch):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    validate_deployment_settings(_prod(payment_channels="alipay,wechat"))


def test_deployment_validation_skipped_in_development():
    # 开发环境即便多 worker / 沙箱也不阻断
    s = Settings(app_env="development", payment_channels="sandbox",
                 database_url="sqlite:///:memory:")
    validate_deployment_settings(s)  # 不抛


def test_compliant_production_settings_start(monkeypatch, tmp_path):
    """端到端：合规生产变量能通过安全+部署校验；弱配置被拦截。"""
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    db_file = tmp_path / "prod.db"
    s = _prod(database_url=f"sqlite:///{db_file}")
    validate_security_settings(s)
    validate_deployment_settings(s)  # 不抛即通过


# ============================================================
# 3. 结构化日志：JSON 输出 + request_id + 敏感信息脱敏
# ============================================================
def _make_record(msg, **extra):
    record = logging.LogRecord(
        name="formfit", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )
    for k, v in extra.items():
        setattr(record, k, v)
    return record


def test_json_formatter_includes_time_level_and_request_id():
    from app.core.logging_config import request_id_ctx
    token = request_id_ctx.set("req-xyz")
    try:
        out = _JsonFormatter().format(_make_record("hello", event="http_request",
                                                  method="GET", path="/x", status=200))
    finally:
        request_id_ctx.reset(token)
    payload = json.loads(out)
    assert payload["level"] == "INFO"
    assert payload["request_id"] == "req-xyz"
    assert payload["event"] == "http_request"
    assert payload["method"] == "GET"
    assert payload["status"] == 200
    assert "time" in payload


def test_json_formatter_redacts_sensitive_substrings():
    out = _JsonFormatter().format(_make_record("user logged in with jwt_secret=abc123"))
    payload = json.loads(out)
    assert "abc123" not in payload["msg"]
    assert "redacted" in payload["msg"]


def test_sanitize_headers_strips_auth_and_cookie():
    safe = sanitize_headers({
        "Authorization": "Bearer xxx",
        "Cookie": "session=yyy",
        "X-Request-ID": "z",
        "Content-Type": "application/json",
    })
    assert "Authorization" not in safe
    assert "Cookie" not in safe
    assert safe["X-Request-ID"] == "z"
    assert safe["Content-Type"] == "application/json"


def test_configure_logging_writes_json_to_stdout(capsys):
    configure_logging("INFO")
    logging.getLogger("formfit.test").info("结构化日志探针", extra={"event": "probe"})
    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["msg"] == "结构化日志探针"
    assert payload["event"] == "probe"
