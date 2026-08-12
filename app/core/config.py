"""应用配置：从 .env 读取，集中管理。"""
import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# 项目根目录（app/core/config.py 的上三级）
BASE_DIR = Path(__file__).resolve().parents[2]
DATASET_DIR = BASE_DIR / "exercises-dataset"
EXERCISES_JSON = DATASET_DIR / "data" / "exercises.json"
UPLOAD_DIR = BASE_DIR / "app" / "static" / "uploads"

# 已知的"默认/占位"密钥值：生产环境命中这些值一律拒绝启动。
# 注意这里同时列出 .env.example 中的占位值，避免有人直接复制 example 上线。
DEFAULT_JWT_SECRETS = {
    "dev-only-change-me",
    "change-me-to-a-long-random-string",
    "changeme",
    "secret",
}
DEFAULT_ADMIN_PASSWORDS = {"change-me-admin", "admin", "password"}
DEFAULT_ADMIN_SESSION_SECRETS = {"dev-only-change-me", "change-me", "changeme"}

# 开发环境默认放开的本地来源（App/Web 本地调试）
_DEV_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 运行环境：development / production（用 APP_ENV 区分）
    app_env: str = "development"

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

    # ---- Web Cookie 会话（ADR-4：与 Bearer JWT 共存）----
    # 浏览器端会话 cookie 名（HttpOnly，承载与 App 完全相同的 JWT），作用域 /api。
    web_cookie_name: str = "ff_session"
    # CSRF 双提交 cookie 名（**不加** HttpOnly，供前端 JS 读取后回填 X-CSRF-Token）。
    csrf_cookie_name: str = "csrftoken"
    # cookie 作用路径：仅在 /api 下携带，缩小暴露面。
    web_cookie_path: str = "/api"
    # 是否给会话 cookie 加 Secure。None 表示跟随 is_production（生产 true，本地 HTTP 开发 false）。
    # 显式设置 WEB_COOKIE_SECURE=true/false 可覆盖。
    web_cookie_secure: bool | None = None
    # SameSite 策略：Lax 允许顶层导航带 cookie，跨站 POST 不携带，兼顾 PWA 跳转与 CSRF 防护。
    web_cookie_samesite: str = "lax"

    # 管理员
    admin_email: str = "admin@formfit.local"
    admin_password: str = "change-me-admin"
    # 后台 session 独立签名密钥（必须与 jwt_secret 不同）；
    # 留空时开发环境回退到 jwt_secret（仅 warning），生产环境必须显式设置。
    admin_session_secret: str = ""
    admin_session_max_age_seconds: int = 60 * 60 * 24 * 7  # 7 天

    # CORS 来源白名单，逗号分隔；留空时：开发放开本地，生产不放通配（仅同源）
    cors_origins: str = ""

    # 上传
    upload_max_bytes: int = 10 * 1024 * 1024  # 10MB

    # 数据库
    database_url: str = "sqlite:///./formfit.db"

    # 服务
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    # 日志级别（DEBUG/INFO/WARNING/ERROR），生产默认 INFO
    log_level: str = "INFO"

    # 业务
    app_name: str = "FormFit"
    upload_dir: Path = UPLOAD_DIR

    # ---- 限流（应用层兜底，单位：次/时间窗口）----
    # 格式 "N/period"，period 如 second/minute/hour/day。
    # 是否部署在可信反向代理之后：仅当为 true 时才采信 X-Forwarded-For
    # 取客户端 IP；否则一律用直连地址，防止客户端伪造/轮换 XFF 绕过限流。
    trusted_proxy_enabled: bool = False
    rate_limit_register: str = "10/minute"
    rate_limit_login: str = "20/minute"
    rate_limit_assess: str = "30/minute"
    rate_limit_generate_plan: str = "20/minute"
    rate_limit_create_order: str = "30/minute"

    # ---- 免费档月度配额（共享池）----
    # 免费用户体态评估 + AI 计划生成**共享**每月可用次数（按自然月 UTC）。
    # 两功能合计达到该上限即返回 402 quota_exhausted。设为 0 表示免费档完全无额度；
    # PRO 用户不受此限。
    free_quota_per_month: int = 5

    # ---- 支付 ----
    # 启用的渠道，逗号分隔：sandbox,apple,alipay,wechat（首发渠道待产品确认）
    payment_channels: str = "sandbox"
    payment_callback_base_url: str = "http://127.0.0.1:8000"

    # 下单 Kill Switch：v1 为免费自用版，默认硬关闭真实下单。
    # 关闭时 POST /api/payment/orders 直接返回 403 checkout_disabled，不进 provider、
    # 不建 Order、不产生支付凭证；只读接口（套餐目录、会员状态）仍可用。
    # 这是运行时配置级开关，线上紧急关闭只需改环境变量无需发版。
    checkout_enabled: bool = False

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
    # APIv3 密钥（32 字节），用于回调解密 AES-256-GCM
    wechat_api_v3_key: str = ""
    # 微信支付平台证书/公钥（PEM 文本），用于校验回调 Wechatpay-Signature。
    # 生产应通过微信平台证书下载器定期轮换；这里支持直接注入一份当前生效的证书。
    wechat_platform_cert: str = ""
    # 商户 API 私钥（PEM，apiclient_key.pem 内容），用于请求签名
    wechat_mch_private_key: str = ""
    # 商户证书序列号
    wechat_mch_serial_no: str = ""
    # 微信支付回调通知地址
    wechat_notify_url: str = ""

    # ---- 派生属性 ----
    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    @property
    def web_cookie_secure_effective(self) -> bool:
        """会话 cookie 是否加 Secure：显式配置优先，否则生产 true、本地 HTTP 开发 false。"""
        if self.web_cookie_secure is not None:
            return self.web_cookie_secure
        return self.is_production

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.strip().startswith("sqlite")

    @property
    def payment_channel_list(self) -> list[str]:
        """解析 PAYMENT_CHANNELS 为小写渠道名列表。"""
        return [
            c.strip().lower()
            for c in self.payment_channels.split(",")
            if c.strip()
        ]

    @property
    def worker_count(self) -> int:
        """uvicorn worker 数：读 WEB_CONCURRENCY（uvicorn 官方约定的环境变量）。

        未设置时视为 1。SQLite 生产部署的硬约束是单 worker（见 validate_deployment）。
        """
        raw = os.environ.get("WEB_CONCURRENCY", "").strip()
        if not raw:
            return 1
        try:
            return max(1, int(raw))
        except ValueError:
            return 1

    @property
    def cors_origin_list(self) -> list[str]:
        """解析 cors_origins 为去空白后的来源列表。"""
        if not self.cors_origins.strip():
            return []
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def effective_cors_origins(self) -> list[str]:
        """返回实际生效的 CORS 来源：

        - 显式配置了 cors_origins：以配置为准（生产/开发都适用）。
        - 未配置且为开发：放开本地常用端口。
        - 未配置且为生产：返回空列表（仅同源，绝不使用 "*"）。
        """
        configured = self.cors_origin_list
        if configured:
            return configured
        if self.is_production:
            return []
        return list(_DEV_CORS_ORIGINS)

    def admin_secret_key(self) -> str:
        """后台 session 签名密钥：优先独立配置；
        开发环境留空时回退到 jwt_secret 并 warning，生产环境须显式设置。"""
        if self.admin_session_secret.strip():
            return self.admin_session_secret
        if self.is_production:
            # 不应走到这里——validate_security_settings 会先拦截；双保险。
            raise RuntimeError("生产环境必须设置 ADMIN_SESSION_SECRET")
        logger.warning(
            "ADMIN_SESSION_SECRET 未设置，开发环境回退到 JWT_SECRET；"
            "生产环境务必配置独立密钥"
        )
        return self.jwt_secret


def validate_security_settings(settings: Settings) -> None:
    """生产环境安全启动校验：默认/占位密钥直接抛错中止启动；
    开发环境仅记录 warning，不阻断。"""
    problems: list[str] = []

    if settings.jwt_secret.strip() in DEFAULT_JWT_SECRETS or len(settings.jwt_secret) < 16:
        problems.append(
            "JWT_SECRET 仍为默认/占位值或长度不足(<16)，请用 `openssl rand -hex 32` 生成"
        )
    if settings.admin_password.strip() in DEFAULT_ADMIN_PASSWORDS or len(settings.admin_password) < 8:
        problems.append(
            "ADMIN_PASSWORD 仍为默认/弱口令，请设置为强密码（≥8 位）"
        )
    secret = settings.admin_session_secret.strip()
    if not secret:
        problems.append(
            "ADMIN_SESSION_SECRET 未设置，请生成独立于 JWT_SECRET 的随机串"
        )
    elif secret in DEFAULT_ADMIN_SESSION_SECRETS or len(secret) < 16:
        problems.append("ADMIN_SESSION_SECRET 过弱或为默认值，请用 `openssl rand -hex 32` 生成")
    elif secret == settings.jwt_secret:
        problems.append("ADMIN_SESSION_SECRET 必须与 JWT_SECRET 不同")

    if settings.is_production and problems:
        raise RuntimeError(
            "生产环境安全校验失败，拒绝启动：\n  - " + "\n  - ".join(problems)
        )
    for p in problems:
        logger.warning("安全配置提示：%s", p)


def validate_deployment_settings(settings: Settings) -> None:
    """生产环境部署形态校验：SQLite 单 worker、禁用沙箱支付、禁用内存库。

    这些是 v1 单容器/单实例低容量目标的硬约束；任何多 worker/多副本需求必须重新评审。
    """
    if not settings.is_production:
        return

    problems: list[str] = []

    # SQLite 不支持多进程并发写：必须单 worker、单容器。
    if settings.is_sqlite and settings.worker_count > 1:
        problems.append(
            "SQLite 生产部署仅允许单 worker/单容器（WEB_CONCURRENCY 必须为 1）；"
            "多 worker 会导致写锁竞争与数据库损坏"
        )

    # 内存库在容器重启后数据全丢，生产绝不允许。
    if ":memory:" in settings.database_url:
        problems.append("生产环境不得使用 SQLite 内存库（:memory:），请挂载持久卷")

    # 沙箱支付仅供本地联调，生产启用会产生无法真实结算的订单。
    if "sandbox" in settings.payment_channel_list:
        problems.append(
            "生产环境不得启用 sandbox 支付渠道；真实凭证就绪前请把 PAYMENT_CHANNELS 置空"
        )

    if problems:
        raise RuntimeError(
            "生产环境部署校验失败，拒绝启动：\n  - " + "\n  - ".join(problems)
        )

    # 下单 Kill Switch：v1 免费自用版生产默认应为关闭。此处仅告警不阻断，
    # 以便将来商业化时无需改代码即可打开；但打开必须是显式、有意识的运维决策。
    if settings.checkout_enabled:
        logger.warning(
            "生产环境 CHECKOUT_ENABLED=true：真实下单已开启，请确认支付渠道与结算流程就绪"
        )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    validate_security_settings(settings)
    validate_deployment_settings(settings)
    return settings


settings = get_settings()
