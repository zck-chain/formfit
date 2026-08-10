"""应用配置：从 .env 读取，集中管理。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（app/core/config.py 的上三级）
BASE_DIR = Path(__file__).resolve().parents[2]
DATASET_DIR = BASE_DIR / "exercises-dataset"
EXERCISES_JSON = DATASET_DIR / "data" / "exercises.json"
UPLOAD_DIR = BASE_DIR / "app" / "static" / "uploads"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DeepSeek
    deepseek_api_key: str = "sk-placeholder"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 通义千问 DashScope（Qwen-VL）
    dashscope_api_key: str = "sk-placeholder"
    dashscope_vl_model: str = "qwen-vl-max-latest"

    # 鉴权
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 天

    # 管理员
    admin_email: str = "admin@formfit.local"
    admin_password: str = "change-me-admin"

    # 数据库
    database_url: str = "sqlite:///./formfit.db"

    # 服务
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    # 业务
    app_name: str = "FormFit"
    upload_dir: Path = UPLOAD_DIR


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
