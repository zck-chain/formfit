"""Web 后台管理员的 session 鉴权（基于 itsdangerous 签名 cookie）。

与 App 端的 JWT 相互独立：
- 使用独立的签名密钥 ``admin_session_secret``（不与 ``jwt_secret`` 共用，
  避免一处泄露波及两套体系）；
- 使用 ``URLSafeTimedSerializer`` 自带的 ``max_age`` 控制有效期；
- 载荷携带 ``ver``（用户的 session_version），服务端可通过递增该值
  使已签发 cookie 立即失效（登出/改密/吊销）。
"""
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings

COOKIE_NAME = "formfit_admin"


def _serializer() -> URLSafeTimedSerializer:
    # 每次取当前密钥，便于测试在重载 settings 后生效；生产中密钥恒定。
    return URLSafeTimedSerializer(
        settings.admin_secret_key(), salt="formfit-admin-session"
    )


def create_session(user_id: int, session_version: int = 0) -> str:
    return _serializer().dumps({"uid": int(user_id), "ver": int(session_version)})


def read_session_payload(token: str | None) -> tuple[int, int] | None:
    """校验签名与时效，返回 ``(user_id, session_version)``；无效则 None。"""
    if not token:
        return None
    try:
        data = _serializer().loads(
            token, max_age=settings.admin_session_max_age_seconds
        )
        return int(data["uid"]), int(data.get("ver", 0))
    except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
        return None
