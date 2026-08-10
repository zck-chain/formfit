"""CORS 收敛逻辑测试。"""
import importlib

import pytest


def _reload_main(monkeypatch, **settings_overrides):
    """用指定的 settings 属性重新加载 app.main，返回模块。"""
    from app.core import config

    for k, v in settings_overrides.items():
        monkeypatch.setattr(config.settings, k, v)
    import app.main as main

    return importlib.reload(main)


def test_wildcard_origins_force_credentials_off(monkeypatch):
    """开发环境回退到 * 时，credentials 必须为 False，杜绝 *+credentials。"""
    main = _reload_main(monkeypatch, cors_origins="", environment="development")
    assert main._cors_origins == ["*"]
    assert main._effective_credentials is False


def test_explicit_whitelist_allows_credentials(monkeypatch):
    main = _reload_main(
        monkeypatch,
        cors_origins="https://app.example.com,https://admin.example.com",
        environment="production",
    )
    assert main._cors_origins == [
        "https://app.example.com",
        "https://admin.example.com",
    ]
    assert main._effective_credentials is True


def test_production_empty_whitelist_disables_cors(monkeypatch):
    # 生产缺白名单：兜底返回空列表（启动校验会先拒绝；这里验证兜底行为）
    main = _reload_main(monkeypatch, cors_origins="   ", environment="production")
    assert main._cors_origins == []
    assert main._effective_credentials is False


def test_no_wildcard_plus_credentials_anywhere(monkeypatch):
    """无论配置如何，都不应出现 allow_origins=['*'] 且 allow_credentials=True。"""
    main = importlib.import_module("app.main")
    main = importlib.reload(main)
    if "*" in main._cors_origins:
        assert main._effective_credentials is False
