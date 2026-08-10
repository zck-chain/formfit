"""Web 后台管理员的 session 鉴权（基于 itsdangerous 签名 cookie）。

与 App 端的 JWT 相互独立：后台是浏览器人工操作，用 session cookie 更合适。
使用独立的 admin_session_secret，避免与 JWT secret 复用导致一处泄漏牵连两端。
"""
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings

# 独立 secret + 独立 salt，与 JWT 完全隔离。
_serializer = URLSafeTimedSerializer(
    settings.admin_session_secret, salt="formfit-admin-session-v2"
)
COOKIE_NAME = "formfit_admin"
# 后台会话有效期：7 天（与 cookie max_age 对齐）
SESSION_MAX_AGE = 60 * 60 * 24 * 7


def create_session(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session(token: str | None) -> int | None:
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return int(data["uid"])
    except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
        return None
