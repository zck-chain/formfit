"""Web 后台管理员的 session 鉴权（基于 itsdangerous 签名 cookie）。

与 App 端的 JWT 相互独立：后台是浏览器人工操作，用 session cookie 更合适。
"""
from itsdangerous import BadSignature, URLSafeSerializer

from app.core.config import settings

_serializer = URLSafeSerializer(settings.jwt_secret, salt="formfit-admin-session")
COOKIE_NAME = "formfit_admin"


def create_session(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session(token: str | None) -> int | None:
    if not token:
        return None
    try:
        data = _serializer.loads(token)
        return int(data["uid"])
    except (BadSignature, KeyError, ValueError, TypeError):
        return None
