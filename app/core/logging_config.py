"""生产环境结构化日志配置。

- 输出到 stdout/stderr，由 Docker / 1Panel 负责采集与轮转。
- 每行一条 JSON，至少包含时间、级别、logger、事件与请求标识（若在请求上下文中）。
- 严禁在日志中记录 JWT、密钥、完整支付回调、用户照片等敏感信息：
  本模块只负责格式，敏感字段的过滤由调用方保证（见 app.api.routes.payment 仅记录错误摘要）。
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

# 请求标识：由 RequestIdMiddleware 在每个请求入口设置，日志记录时自动带出。
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

# 访问日志等事件里绝不允许出现的请求/响应头，按小写匹配。
SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-sandbox-signature"}

# 记录日志时绝不允许带出的字段名（小写子串匹配），兜底防止密钥/令牌泄露。
_SENSITIVE_KEY_SUBSTRINGS = (
    "password",
    "secret",
    "token",
    "jwt",
    "private_key",
    "api_key",
    "authorization",
)


def sanitize_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """返回去掉敏感头的副本，用于访问日志。"""
    if not headers:
        return {}
    result: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in SENSITIVE_HEADERS:
            continue
        result[k] = v
    return result


class _JsonFormatter(logging.Formatter):
    """把 LogRecord 渲染成单行 JSON。

    extra 里传入的字段会平铺到输出；event 字段用于区分事件类型。
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_ctx.get()
        if rid:
            payload["request_id"] = rid

        # 把 extra 中已知的结构化字段带出来
        for key in ("event", "method", "path", "status", "duration_ms", "client_ip"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        # 兜底：若 msg 中疑似包含密钥字段，做一次脱敏（防御性，不替代调用方约束）
        for sub in _SENSITIVE_KEY_SUBSTRINGS:
            if sub in payload["msg"].lower():
                payload["msg"] = "[redacted possible secret in message]"
                break

        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """配置根日志：JSON 格式输出到 stdout，级别由 LOG_LEVEL 控制。

    幂等：多次调用只保留一个 handler，避免 uvicorn reload 时重复打印。
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    # 清除既有 handler（含 basicConfig 与之前的配置），保证生产只有 JSON stdout。
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)

    # 降低第三方库的噪音，但不吞掉警告与错误。
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).setLevel(logging.WARNING)
