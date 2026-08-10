"""阿里云通义千问 Qwen-VL 客户端：看用户照片/视频帧，给体型定性评估。

使用 DashScope 的 OpenAI 兼容端点：
    https://dashscope.aliyuncs.com/compatible-mode/v1

未配置 key 时返回 mock 评估，便于先跑通流程。
"""
import base64
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

_DUMMY_KEYS = {"", "sk-placeholder", "sk-your-dashscope-key", "change-me"}


def vl_configured() -> bool:
    return settings.dashscope_api_key not in _DUMMY_KEYS


def _to_data_url(path: str | Path) -> str:
    """把本地图片转成 data: url；视频只取首帧（这里简化为直接传图片）。"""
    p = Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def assess_body(
    image_path: str | Path,
    *,
    height_cm: float | None = None,
    weight_kg: float | None = None,
    age: int | None = None,
    gender: str | None = None,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """根据用户体态照片与基础数据，给出增肌/减脂/康复方向的定性评估。

    返回固定结构：
    {
        "direction": "gain" | "fat_loss" | "rehab" | "maintain",
        "body_type": "...",        # 体型/体态文字
        "summary": "...",          # 给用户的中文总结与建议
        "observed": ["...", ...],  # 观察到的体态要点
        "safety_notes": "..."      # 康复/安全提示
    }
    """
    if not vl_configured():
        logger.warning("DashScope key 未配置，返回 mock 视觉评估")
        return _mock_assessment(height_cm, weight_kg)

    bmi = None
    if height_cm and weight_kg:
        bmi = round(weight_kg / ((height_cm / 100) ** 2), 1)

    system = (
        "你是一名专业健身教练，正在查看用户的体态照片并结合身高体重做初步评估。"
        "只做定性判断，不做医学诊断、不替代医生。"
        "必须只返回 JSON，字段：direction(值为 gain 增肌 / fat_loss 减脂 / "
        "rehab 存在体态问题需先做康复性调整并建议就医 / maintain 维持)、"
        "body_type(字符串，描述你观察到的体型/体态)、"
        "observed(字符串数组，3-5 条观察要点)、"
        "summary(给用户的中文通俗建议，150字内)、"
        "safety_notes(安全/就医提示，如无明显问题给一句鼓励)。"
    )
    user_text = (
        f"用户基础数据：性别={gender or '未知'}，年龄={age or '未知'}，"
        f"身高={height_cm or '未知'}cm，体重={weight_kg or '未知'}kg，"
        f"估算BMI={bmi or '未知'}。"
        "请结合照片给出评估方向。"
    )

    payload = {
        "model": settings.dashscope_vl_model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": _to_data_url(image_path)}},
                    {"type": "text", "text": user_text},
                ],
            },
        ],
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{DASHSCOPE_BASE}/chat/completions", headers=headers, json=payload
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"] or "{}"

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Qwen-VL 返回非合法 JSON：%s", text[:200])
        result = {"direction": "maintain", "summary": text, "body_type": "", "observed": []}

    result.setdefault("direction", "maintain")
    result.setdefault("summary", "")
    result.setdefault("observed", [])
    result.setdefault("safety_notes", "本评估为 AI 初步参考，不适用于医学诊断。")
    return result


def _mock_assessment(
    height_cm: float | None, weight_kg: float | None
) -> dict[str, Any]:
    bmi = None
    if height_cm and weight_kg:
        bmi = round(weight_kg / ((height_cm / 100) ** 2), 1)
    direction = "maintain"
    if bmi:
        if bmi < 18.5:
            direction = "gain"
        elif bmi >= 24:
            direction = "fat_loss"
    return {
        "direction": direction,
        "body_type": "（未配置 Qwen-VL，仅根据 BMI 占位推断）",
        "observed": ["这是未配置视觉模型时的占位结果"],
        "summary": (
            f"估算 BMI={bmi or '未知'}。请在 .env 中填入 DASHSCOPE_API_KEY 启用真实图片评估。"
        ),
        "safety_notes": "本评估为 AI 初步参考，不适用于医学诊断；如有疼痛或伤病请就医。",
    }
