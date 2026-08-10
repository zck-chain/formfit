"""配置层与生产启动安全门禁测试。"""
import pytest

from app.core.config import ProductionConfigError, Settings


def _prod(**overrides) -> Settings:
    """构造一个生产环境 Settings，默认值全部安全，可按需覆盖。"""
    base = dict(
        environment="production",
        jwt_secret="x" * 40,
        admin_session_secret="y" * 40,
        admin_password="a-strong-passphrase-123",
        cors_origins="https://app.example.com",
    )
    base.update(overrides)
    return Settings(**base)


def test_validate_production_passes_with_safe_values():
    settings = _prod()
    settings.validate_production()  # 不应抛异常


@pytest.mark.parametrize(
    "field,value",
    [
        ("jwt_secret", "dev-only-change-me"),
        ("jwt_secret", "short"),
        ("admin_session_secret", "dev-admin-session-change-me"),
        ("admin_password", "change-me-admin"),
        ("admin_password", "short"),
    ],
)
def test_validate_production_rejects_placeholder_secrets(field, value):
    settings = _prod(**{field: value})
    with pytest.raises(ProductionConfigError):
        settings.validate_production()


def test_validate_production_rejects_shared_session_secret():
    settings = _prod(jwt_secret="same-secret-value-1234567890", admin_session_secret="same-secret-value-1234567890")
    with pytest.raises(ProductionConfigError):
        settings.validate_production()


def test_validate_production_rejects_wildcard_cors():
    settings = _prod(cors_origins="*")
    with pytest.raises(ProductionConfigError):
        settings.validate_production()


def test_validate_production_rejects_empty_cors():
    settings = _prod(cors_origins="")
    with pytest.raises(ProductionConfigError):
        settings.validate_production()


def test_development_does_not_enforce_production_rules():
    # 开发环境允许占位值（便于本地直接启动）
    settings = Settings(environment="development")
    settings.validate_production()  # 非生产环境直接返回，不抛


def test_invalid_environment_rejected():
    with pytest.raises(Exception):
        Settings(environment="staging")


def test_cors_origin_list_parsing():
    settings = Settings(cors_origins="https://a.com, https://b.com ,")
    assert settings.cors_origin_list == ["https://a.com", "https://b.com"]


def test_admin_session_secret_is_independent_of_jwt():
    settings = Settings(
        jwt_secret="jwt-secret-value-1234567890",
        admin_session_secret="session-secret-value-abcdef",
    )
    assert settings.admin_session_secret != settings.jwt_secret
