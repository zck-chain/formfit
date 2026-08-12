"""Web 端 Cookie 会话与 CSRF 双提交工具（ADR-4）。

与 App 端 Bearer JWT 共存：
- ``ff_session`` cookie 承载与 App **完全相同**的 JWT（复用 create_access_token），
  HttpOnly，前端 JS 不可读，防 XSS 窃取；
- ``csrftoken`` cookie **不加** HttpOnly，供前端 JS 读取后在写操作请求头
  ``X-CSRF-Token`` 回填，服务端做常量时间比对（双提交 cookie 模式）。

native 走 Authorization: Bearer，不依赖 cookie，因此不要求 CSRF。
"""
from __future__ import annotations

import secrets

from fastapi import Request, Response

from app.core.config import settings

# 写操作方法：cookie 认证下必须携带并通过 CSRF 校验。
_CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# CSRF 请求头名。
CSRF_HEADER_NAME = "x-csrf-token"


def generate_csrf_token() -> str:
    """生成一个 URL 安全的随机 CSRF token（32 字节熵）。"""
    return secrets.token_urlsafe(32)


def set_session_cookie(response: Response, token: str) -> None:
    """下发 HttpOnly 会话 cookie，承载 JWT。"""
    response.set_cookie(
        key=settings.web_cookie_name,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.web_cookie_secure_effective,
        samesite=settings.web_cookie_samesite,
        path=settings.web_cookie_path,
    )


def set_csrf_cookie(response: Response, token: str) -> None:
    """下发 CSRF cookie：可读（不加 HttpOnly），供前端 JS 双提交。"""
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=False,
        secure=settings.web_cookie_secure_effective,
        samesite=settings.web_cookie_samesite,
        path=settings.web_cookie_path,
    )


def clear_session_cookies(response: Response) -> None:
    """登出时清除会话与 CSRF cookie。delete_cookie 的 path/secure/samesite/domain
    必须与 set_cookie 完全一致，浏览器才会真正删除。"""
    response.delete_cookie(
        key=settings.web_cookie_name,
        path=settings.web_cookie_path,
        secure=settings.web_cookie_secure_effective,
        samesite=settings.web_cookie_samesite,
    )
    response.delete_cookie(
        key=settings.csrf_cookie_name,
        path=settings.web_cookie_path,
        secure=settings.web_cookie_secure_effective,
        samesite=settings.web_cookie_samesite,
    )


def read_bearer_token(request: Request) -> str | None:
    """从 Authorization 头提取 Bearer token；无则 None。"""
    header = request.headers.get("authorization")
    if not header:
        return None
    # OAuth2 自带 scheme 解析；这里只做轻量提取，避免与 oauth2_scheme 重复依赖。
    parts = header.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def read_session_token(request: Request) -> str | None:
    """从会话 cookie 读取 JWT；无则 None。"""
    return request.cookies.get(settings.web_cookie_name)


def csrf_required(request: Request) -> bool:
    """判断该请求是否需要 CSRF 校验：写方法 + 无 Bearer 头 + 携带会话 cookie。

    - 安全方法（GET/HEAD/OPTIONS/TRACE）不改变服务端状态，免校验；
    - Bearer 认证来自 native，浏览器不会自动附带，不存在跨站伪造，免校验；
    - 匿名且无会话 cookie 时没有任何身份可伪造，由后续认证返回 401 即可，
      不应抢先返回 403（否则匿名写操作的错误码被 CSRF 吞掉）。
    """
    if request.method not in _CSRF_METHODS:
        return False
    # 显式带了 Authorization 头的请求视为 Bearer/native 链路，不要求 CSRF。
    if read_bearer_token(request) is not None:
        return False
    # 仅当浏览器自动携带了会话 cookie 时才存在跨站伪造面。
    return read_session_token(request) is not None


def validate_csrf(request: Request) -> bool:
    """常量时间比对 X-CSRF-Token 请求头与 csrftoken cookie。两者都存在且相等才通过。"""
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get(CSRF_HEADER_NAME)
    if not cookie_token or not header_token:
        return False
    return secrets.compare_digest(cookie_token, header_token)
