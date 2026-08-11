"""应用层限流（slowapi）：作为反向代理/网关限流之外的兜底。

生产若已有网关（Nginx/APISIX/云 WAF）做限流，这里仍保留一层以保护未鉴权
的注册/登录与昂贵的 AI 接口。存储默认进程内 MemoryStorage；多实例部署时
应改为共享存储（Redis，storage_uri="redis://..."），否则限流是 per-instance。

阈值全部走配置（RATE_LIMIT_*），可在 .env 按部署形态调整。
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.security import decode_token


def client_ip(request) -> str:
    """限流用的客户端 IP。

    仅当部署在可信反向代理之后且 ``TRUSTED_PROXY_ENABLED=true`` 时才采信
    ``X-Forwarded-For``，否则一律用直连地址，防止客户端通过伪造/轮换 XFF
    绕过注册、登录等未鉴权接口的暴力破解限流。
    """
    if settings.trusted_proxy_enabled:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return get_remote_address(request)


def _ip_key(request) -> str:
    """默认限流维度：客户端 IP。"""
    return client_ip(request)


def user_or_ip_key(request) -> str:
    """已鉴权接口的限流维度：优先按登录用户，凭据缺失/无效时回退 IP。

    在 NAT/运营商级 NAT 后，不同用户不会共用同一 IP 配额互相误伤；
    同时单个用户即便轮换来源 IP 也无法绕过限流。IP 维度作为未登录兜底保留。
    """
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        token = auth[7:].strip()
        try:
            payload = decode_token(token)
        except Exception:  # noqa: BLE001  限流键解析绝不能影响正常请求
            payload = None
        if payload and payload.get("sub"):
            return f"user:{payload['sub']}"
    return client_ip(request)


limiter = Limiter(
    key_func=_ip_key,
    # 限流后端异常不应拖垮正常请求（记录即可）
    swallow_errors=True,
    key_prefix="formfit",
)
