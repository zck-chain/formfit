"""应用配置：从 .env 读取，集中管理。"""
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（app/core/config.py 的上三级）
BASE_DIR = Path(__file__).resolve().parents[2]
DATASET_DIR = BASE_DIR / "exercises-dataset"
EXERCISES_JSON = DATASET_DIR / "data" / "exercises.json"
UPLOAD_DIR = BASE_DIR / "app" / "static" / "uploads"

# 已知的占位/弱密钥：生产环境若仍使用这些值，应用必须拒绝启动。
# 同时用于判断 AI 厂商 key 是否为占位（不阻断启动，仅决定是否走 mock）。
PLACEHOLDER_VALUES = {
    "",
    "change-me",
    "change-me-admin",
    "change-me-to-a-long-random-string",
    "dev-only-change-me",
    "dev-admin-session-change-me",
    "placeholder",
    "secret",
    "sk-placeholder",
    "sk-your-deepseek-key",
    "sk-your-dashscope-key",
}

# 上传默认约束（体态评估图片）。10 MiB 足够手机直出照片压缩后使用，
# 同时阻断超大请求耗尽内存/磁盘。
DEFAULT_UPLOAD_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_UPLOAD_ALLOWED_TYPES = "image/jpeg,image/png,image/webp"


class ProductionConfigError(RuntimeError):
    """生产环境配置不安全时抛出（拒绝启动）。"""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 运行环境：development | production
    # production 下：强制安全 cookie、拒绝占位密钥、CORS 不得使用通配符。
    environment: str = "development"

    # DeepSeek
    deepseek_api_key: str = "sk-placeholder"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 通义千问 DashScope（Qwen-VL）
    dashscope_api_key: str = "sk-placeholder"
    dashscope_vl_model: str = "qwen-vl-max-latest"

    # 鉴权（App 端 JWT）
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 天

    # Web 后台 session（独立于 JWT secret，降低一处泄漏牵连两端的风险）
    admin_session_secret: str = "dev-admin-session-change-me"

    # 管理员
    admin_email: str = "admin@formfit.local"
    admin_password: str = "change-me-admin"

    # CORS：逗号分隔的来源白名单（如 https://app.example.com,https://admin.example.com）。
    # "*" 仅允许在 development 且不与 credentials 同开。
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    # 后台是浏览器人工操作，需要带 cookie；App 端走 Bearer 不依赖 CORS credentials。
    cors_allow_credentials: bool = True

    # 数据库
    database_url: str = "sqlite:///./formfit.db"

    # 服务
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    # 上传约束
    upload_max_bytes: int = DEFAULT_UPLOAD_MAX_BYTES
    upload_allowed_types: str = DEFAULT_UPLOAD_ALLOWED_TYPES

    # 业务
    app_name: str = "FormFit"
    upload_dir: Path = UPLOAD_DIR

    @field_validator("environment")
    @classmethod
    def _normalize_environment(cls, v: str) -> str:
        v = (v or "development").strip().lower()
        if v not in ("development", "production"):
            raise ValueError("environment 只能是 development 或 production")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        """解析逗号分隔的来源，去掉空白与空项。"""
        return [o.strip() for o in (self.cors_origins or "").split(",") if o.strip()]

    @property
    def upload_allowed_type_set(self) -> set[str]:
        return {
            t.strip().lower()
            for t in (self.upload_allowed_types or "").split(",")
            if t.strip()
        }

    def validate_production(self) -> None:
        """生产环境启动前的安全门禁。

        检查项：JWT secret、后台 session secret、管理员密码均不得为占位值或过短；
        JWT 与后台 session secret 不得相同；CORS 不得在生产使用通配符 "*"。
        任一不满足则抛 ProductionConfigError，拒绝启动。
        """
        if not self.is_production:
            return

        errors: list[str] = []

        def _check_secret(name: str, value: str, min_len: int = 16) -> None:
            if value.strip().lower() in PLACEHOLDER_VALUES:
                errors.append(f"{name} 仍为占位值，生产环境必须设置随机长字符串")
            elif len(value) < min_len:
                errors.append(f"{name} 长度不足 {min_len} 字符")

        _check_secret("jwt_secret", self.jwt_secret)
        _check_secret("admin_session_secret", self.admin_session_secret)
        # 管理员密码：不强制长度上限，但要求不是默认占位且足够长
        if self.admin_password.strip().lower() in PLACEHOLDER_VALUES:
            errors.append("admin_password 仍为占位值，生产环境必须修改")
        elif len(self.admin_password) < 12:
            errors.append("admin_password 长度不足 12 字符")

        if self.admin_session_secret == self.jwt_secret:
            errors.append("admin_session_secret 不得与 jwt_secret 相同")

        origins = self.cors_origin_list
        if not origins:
            errors.append("cors_origins 未配置，生产环境必须显式列出允许来源")
        if "*" in origins:
            errors.append("cors_origins 不得在生产环境使用通配符 *")

        if errors:
            raise ProductionConfigError(
                "生产环境安全校验未通过，拒绝启动：\n  - " + "\n  - ".join(errors)
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
