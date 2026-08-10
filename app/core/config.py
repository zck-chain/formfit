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

    # ---- 支付 ----
    # 启用的渠道，逗号分隔：sandbox,apple,alipay,wechat（首发渠道待产品确认）
    payment_channels: str = "sandbox"
    payment_callback_base_url: str = "http://127.0.0.1:8000"

    # 沙箱渠道（本地/联调，无需真实密钥）
    sandbox_secret: str = "sandbox-dev-secret"

    # Apple App Store Server IAP（服务端凭证校验）
    # 共享密钥（App-Specific Shared Secret），用于 verifyReceipt
    apple_shared_secret: str = ""
    # 固定回传的 bundle_id，防跨 App 伪造；留空则不校验
    apple_bundle_id: str = ""
    # true 使用 https://buy.itunes.apple.com（生产），false 使用沙箱 sandbox
    apple_production: bool = False

    # 支付宝（预留，首发渠道确认后启用）
    alipay_app_id: str = ""
    alipay_private_key: str = ""
    alipay_public_key: str = ""
    alipay_callback_url: str = ""

    # 微信支付（预留）
    wechat_app_id: str = ""
    wechat_mch_id: str = ""
    wechat_api_v3_key: str = ""


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
