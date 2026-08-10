"""DeepSeek 文本对话客户端（OpenAI 兼容格式）。

负责：普通对话与基于工具调用(function calling)的计划编排。
未配置真实 key 时自动降级为 mock，方便在没有 API 的情况下跑通流程。
"""
import json
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_DUMMY_KEYS = {"", "sk-placeholder", "sk-your-deepseek-key", "change-me"}


def is_configured() -> bool:
    return settings.deepseek_api_key not in _DUMMY_KEYS


async def chat(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.7,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """调用 chat completions。返回原始 message dict（含 content / tool_calls）。

    返回结构：{"role": "assistant", "content": str|None, "tool_calls": [...]}
    """
    if not is_configured():
        logger.warning("DeepSeek key 未配置，返回 mock 响应")
        return _mock_response(messages, tools)

    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": settings.deepseek_model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]


def _mock_response(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """没配 key 时的占位响应：提示用户去配置，避免流程崩溃。"""
    last_user = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"),
        "",
    )
    content = (
        "【DeepSeek 未配置】这是一条占位回复。请在项目根目录的 .env 中填入 "
        f"DEEPSEEK_API_KEY 后重启服务以启用真实 AI。\n\n你刚才说的是：{last_user!s:.200}"
    )
    return {"role": "assistant", "content": content, "tool_calls": None}


async def chat_json(
    system: str,
    user_content: str,
    *,
    temperature: float = 0.4,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """便捷方法：让模型严格返回 JSON（通过 response_format）。失败时返回 {}。"""
    if not is_configured():
        return {"_mock": True, "hint": "DEEPSEEK_API_KEY 未配置"}

    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"] or "{}"
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("模型返回非合法 JSON：%s", text[:200])
        return {}
