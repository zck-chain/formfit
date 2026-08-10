"""AI 私教：评估 + 问诊 + 计划生成（工具调用循环）。

计划生成流程（DeepSeek function calling）：
1. 把用户档案 + 视觉评估方向 + 问诊答案塞进 system prompt
2. 提供 search_exercises 工具，让模型按需检索真实动作
3. 模型可多次调用工具（不同部位/器械），拿到带 GIF/中文步骤的真实动作
4. 模型最终返回结构化计划 JSON（引用真实 exercise id）
5. 服务端用数据库二次校验每个 id，补齐展示字段，杜绝编造
"""
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.agent import deepseek_client
from app.services import exercise_service as svc

logger = logging.getLogger(__name__)


# ---- 训练分化建议（给模型参考，不强制） ----
_SPLIT_HINT = {
    2: "每周2练：全身训练(Full Body) x2",
    3: "每周3练：推/拉/腿 或 全身 x3",
    4: "每周4练：上肢/下肢 分化 或 推/拉/腿+弱项",
    5: "每周5练：推/拉/腿/肩臂/弱项 或 上身推/上身拉/下肢循环",
    6: "每周6练：推/拉/腿 各两次",
}


# ---- 暴露给 LLM 的工具定义 ----
SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_exercises",
        "description": (
            "按条件从 1324 个真实健身动作库中检索动作。"
            "每次调用针对一个训练目标组合（部位+器械），可多次调用以覆盖计划中的不同训练日。"
            "返回的每个动作都有 id、gif 动图、中文步骤；编排计划时必须引用返回的真实 id。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "categories": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "chest", "back", "shoulders", "upper arms", "lower arms",
                            "upper legs", "lower legs", "waist", "cardio", "neck",
                        ],
                    },
                    "description": "身体部位过滤，英文，如 ['chest','back']",
                },
                "targets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "目标肌过滤，如 ['pectorals','lats']",
                },
                "equipment": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "只保留这些器械（用户可用器械），如 ['dumbbell','body weight']",
                },
                "keyword": {"type": "string", "description": "按动作名模糊搜索，如 squat"},
                "limit": {
                    "type": "integer",
                    "description": "返回数量上限，建议每个训练日 6-10 个",
                    "default": 8,
                },
            },
        },
    },
}


def _execute_tool(db: Session, name: str, args: dict[str, Any],
                  contraindicated_parts: list[str]) -> Any:
    """执行 LLM 请求的工具调用。"""
    if name != "search_exercises":
        return {"error": f"未知工具 {name}"}
    return svc.search_exercises(
        db,
        categories=args.get("categories"),
        targets=args.get("targets"),
        equipment=args.get("equipment"),
        keyword=args.get("keyword"),
        limit=args.get("limit", 8),
        contraindicated_parts=contraindicated_parts,
    )


def _build_system_prompt(profile: dict[str, Any], assessment: dict[str, Any] | None) -> str:
    direction = (assessment or {}).get("direction", "maintain")
    direction_zh = {
        "gain": "增肌为主",
        "fat_loss": "减脂为主（建议加入有氧并控制容量）",
        "rehab": "先做安全调整/康复性训练，避开禁忌部位",
        "maintain": "维持体态、均衡发展",
    }.get(direction, "均衡发展")

    days = profile.get("days_per_week", 3)
    split_hint = _SPLIT_HINT.get(days, f"每周{days}练，合理分化")

    equipment = profile.get("available_equipment") or ["body weight"]
    injuries = profile.get("contraindicated_parts") or []
    injury_notes = profile.get("injury_notes") or ""

    return f"""你是 FormFit 的资深 AI 私教。你要为下面这位用户生成一份安全、可执行的训练计划。

【用户画像】
- 性别：{profile.get('gender') or '未知'}，年龄：{profile.get('age') or '未知'}
- 身高：{profile.get('height_cm') or '未知'}cm，体重：{profile.get('weight_kg') or '未知'}kg
- 训练目标：{profile.get('goal') or '未指定'}（本次 AI 评估方向：{direction_zh}）
- 训练水平：{profile.get('level') or 'beginner'}
- 每周训练天数：{days}（建议分化：{split_hint}）
- 可用器械：{equipment}
- 禁忌/受伤部位：{injuries or '无'} {injury_notes}

【硬性规则】
1. 只能使用 search_exercises 返回的真实动作，严禁编造动作名或 id。
2. 必须尊重用户可用器械：不要安排用户没有的器械。
3. 必须避开禁忌部位相关动作（工具已自动过滤，但你仍需在选动作时二次确认安全）。
4. 每个训练日安排 4-7 个动作，覆盖主项(复合动作) + 辅项(孤立动作)，热身/拉伸可酌情。
5. 组数次数要符合训练水平与目标：新手 3组x8-12次，增肌 3-4组x8-12次，减脂可加入循环/有氧。
6. 最终只输出一个 JSON 对象，结构如下，不要输出任何多余文字：
{{
  "title": "计划标题",
  "goal": "{profile.get('goal') or 'general'}",
  "weeks": 4,
  "days_per_week": {days},
  "notes": "给用户的整体说明与安全提示，150字内",
  "days": [
    {{
      "day_label": "周一·推日",
      "focus": "胸/肩/三头",
      "items": [
        {{"exercise_id": "0025", "sets": 4, "reps": "8-10", "tempo": "2-1-2", "rest_sec": 90, "note": "主项，注意肩胛后收"}}
      ]
    }}
  ]
}}

先用 search_exercises 检索各训练日需要的动作（针对不同部位分别调用，每次 limit 8），
综合所有结果后再输出最终计划 JSON。"""


async def generate_plan(
    db: Session,
    profile: dict[str, Any],
    assessment: dict[str, Any] | None = None,
    *,
    max_tool_rounds: int = 6,
) -> dict[str, Any]:
    """生成完整训练计划。返回可直接回显/入库的 dict。"""
    system_prompt = _build_system_prompt(profile, assessment)
    contra = profile.get("contraindicated_parts") or []

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                "请根据我的情况生成本周训练计划。"
                "先调用 search_exercises 检索动作，再输出最终 JSON 计划。"
            ),
        },
    ]

    # 工具调用循环
    for _ in range(max_tool_rounds):
        message = await deepseek_client.chat(messages, tools=[SEARCH_TOOL], temperature=0.5)
        messages.append(_normalize_message(message))

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            # 没有工具调用，说明模型给出了最终答复
            break

        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            logger.info("LLM 调用工具 %s 参数=%s", name, args)
            result = _execute_tool(db, name, args, contra)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    # 最后一条消息应为计划 JSON
    final_text = message.get("content") or "{}"
    plan_data = _extract_json(final_text)

    if not plan_data or "days" not in plan_data:
        logger.warning("模型未返回有效计划，原文：%s", final_text[:300])
        plan_data = _fallback_plan(db, profile, contra)

    # 用数据库校验并补全每个动作的展示字段（GIF/中文步骤）
    plan_data = _hydrate_plan(db, plan_data)
    return plan_data


def _normalize_message(message: dict[str, Any]) -> dict[str, Any]:
    """把 assistant 消息整理成可回传给 API 的格式。"""
    normalized: dict[str, Any] = {"role": "assistant"}
    if message.get("content") is not None:
        normalized["content"] = message["content"]
    if message.get("tool_calls"):
        normalized["tool_calls"] = message["tool_calls"]
    return normalized


def _extract_json(text: str) -> dict[str, Any]:
    """从模型输出里抠 JSON（容错：去掉 ```json 包裹）。"""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试截取第一个 { 到最后一个 }
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return {}
        return {}


def _hydrate_plan(db: Session, plan: dict[str, Any]) -> dict[str, Any]:
    """校验计划里每个 exercise_id 是否真实存在，并补上 GIF/中文步骤/中文字段。"""
    invalid = 0
    for day in plan.get("days", []):
        hydrated_items = []
        for item in day.get("items", []):
            ex_id = str(item.get("exercise_id", "")).zfill(4) if str(
                item.get("exercise_id", "")
            ).isdigit() else str(item.get("exercise_id", ""))
            ex = svc.get_by_id(db, ex_id)
            if not ex:
                invalid += 1
                continue
            item["exercise_id"] = ex["id"]
            item["name"] = ex["name"]
            item["target_zh"] = ex["target_zh"]
            item["category_zh"] = ex["category_zh"]
            item["equipment_zh"] = ex["equipment_zh"]
            item["gif_url"] = ex["gif_url"]
            item["image"] = ex["image"]
            item["steps_zh"] = ex["steps_zh"]
            hydrated_items.append(item)
        day["items"] = hydrated_items
    if invalid:
        logger.warning("计划中有 %d 个无效动作 ID 已被剔除", invalid)
    return plan


def _fallback_plan(db: Session, profile: dict[str, Any], contra: list[str]) -> dict[str, Any]:
    """模型不可用/输出异常时的保底计划：按可用器械取全身动作，按天轮转避免重复。"""
    equipment = profile.get("available_equipment") or ["body weight"]
    days = max(1, min(6, int(profile.get("days_per_week") or 3)))

    # 为每个主要部位取多个候选动作，再按天轮转分配
    categories = ["chest", "back", "upper legs", "shoulders", "waist", "upper arms"]
    pool: dict[str, list[dict]] = {}
    for cat in categories:
        pool[cat] = svc.search_exercises(
            db, categories=[cat], equipment=equipment, limit=days,
            contraindicated_parts=contra,
        )

    plan_days = []
    for d in range(days):
        items = []
        for cat in categories:
            candidates = pool.get(cat) or []
            if not candidates:
                continue
            ex = candidates[d % len(candidates)]  # 不同天取不同动作
            items.append(
                {
                    "exercise_id": ex["id"],
                    "name": ex["name"],
                    "gif_url": ex["gif_url"],
                    "image": ex["image"],
                    "steps_zh": ex["steps_zh"],
                    "target_zh": ex["target_zh"],
                    "category_zh": ex["category_zh"],
                    "equipment_zh": ex["equipment_zh"],
                    "sets": 3,
                    "reps": "8-12",
                    "rest_sec": 60,
                    "note": "保底计划",
                }
            )
        plan_days.append({"day_label": f"训练日 {d+1}", "focus": "全身", "items": items})

    return {
        "title": "入门全身计划（保底）",
        "goal": profile.get("goal", "general"),
        "weeks": 4,
        "days_per_week": days,
        "notes": "AI 暂不可用，已为你生成一份基础全身计划。配置 DeepSeek key 后可获得更专业的分化计划。",
        "days": plan_days,
    }
