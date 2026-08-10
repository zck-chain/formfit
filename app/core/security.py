"""密码哈希与 JWT 工具。直接使用 bcrypt 库（避免 passlib 与新版 bcrypt 的兼容问题）。"""
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

# bcrypt 只处理前 72 字节，超出会报错；这里主动截断并保证 bytes 类型。
_MAX_BYTES = 72


def _to_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_MAX_BYTES]


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(_to_bytes(password), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str | int, extra: dict[str, Any] | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload: dict[str, Any] = {"sub": str(subject), "exp": expire}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return None
