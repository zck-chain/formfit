"""应用层限流（slowapi）：作为反向代理/网关限流之外的兜底。

生产若已有网关（Nginx/APISIX/云 WAF）做限流，这里仍保留一层以保护未鉴权
的注册/登录与昂贵的 AI 接口。存储默认进程内 MemoryStorage；多实例部署时
应改为共享存储（Redis，storage_uri="redis://..."），否则限流是 per-instance。

阈值全部走配置（RATE_LIMIT_*），可在 .env 按部署形态调整。
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _client_key(request) -> str:
    """优先取 X-Forwarded-For 的首个 IP（反向代理场景），否则用直连地址。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=_client_key,
    # 限流后端异常不应拖垮正常请求（记录即可）
    swallow_errors=True,
    key_prefix="formfit",
)
