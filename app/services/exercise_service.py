"""健身动作检索服务。

这是 AI 智能体编排训练计划时调用的核心"工具"：
- 按身体部位(category)、器械(equipment)、目标肌(target)筛选
- 按用户可用器械过滤
- 按禁忌/受伤部位做启发式排除（安全第一）
- 返回带中文说明与 GIF 的精简动作对象，不把整个数据集塞进 LLM
"""
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Exercise

# 数据集主语言用英文，前端/LLM 统一用中文展示。这里维护映射。
CATEGORY_ZH = {
    "upper arms": "手臂（上臂）",
    "lower arms": "前臂",
    "upper legs": "大腿",
    "lower legs": "小腿",
    "chest": "胸部",
    "back": "背部",
    "shoulders": "肩部",
    "waist": "腰腹核心",
    "cardio": "有氧",
    "neck": "颈部",
}

EQUIPMENT_ZH = {
    "body weight": "自重",
    "dumbbell": "哑铃",
    "barbell": "杠铃",
    "cable": "龙门架/绳索",
    "leverage machine": "固定器械",
    "band": "弹力带",
    "resistance band": "弹力带",
    "smith machine": "史密斯机",
    "kettlebell": "壶铃",
    "weighted": "负重",
    "stability ball": "瑜伽球",
    "ez barbell": "EZ杆",
    "assisted": "辅助式",
    "medicine ball": "药球",
    "rope": "绳索",
}

TARGET_ZH = {
    "abs": "腹肌",
    "biceps": "肱二头肌",
    "triceps": "肱三头肌",
    "pectorals": "胸肌",
    "lats": "背阔肌",
    "delts": "三角肌",
    "quads": "股四头肌",
    "hamstrings": "腘绳肌",
    "glutes": "臀肌",
    "calves": "小腿",
    "forearms": "前臂",
    "traps": "斜方肌",
    "upper back": "上背",
    "spine": "竖脊肌",
    "abductors": "髋外展肌",
    "adductors": "髋内收肌",
    "cardiovascular system": "心肺系统",
    "serratus anterior": "前锯肌",
    "levator scapulae": "肩胛提肌",
}

# 中文/英文 禁忌部位 → 命中即排除的肌肉关键词（同时匹配 target 与 secondary_muscles）
# 这是启发式安全过滤，最终是否合适由 LLM 判断；宁可保守。
INJURY_KEYWORDS: dict[str, list[str]] = {
    "knees": ["quads", "calves", "soleus", "shins"],
    "膝": ["quads", "calves", "soleus", "shins"],
    "lower back": ["spine", "lower back"],
    "腰": ["spine", "lower back"],
    "腰椎": ["spine", "lower back"],
    "shoulders": ["delts", "deltoids", "rear deltoids", "rotator cuff"],
    "肩": ["delts", "deltoids", "rear deltoids", "rotator cuff"],
    "neck": ["levator scapulae", "sternocleidomastoid", "trapezius", "traps"],
    "颈": ["levator scapulae", "sternocleidomastoid", "trapezius", "traps"],
    "elbows": ["biceps", "triceps"],
    "肘": ["biceps", "triceps"],
    "wrists": ["forearms", "wrist flexors", "wrist extensors"],
    "腕": ["forearms", "wrist flexors", "wrist extensors"],
}


# 数据集媒体文件挂载在 /media/exercises/ 下（见 app/main.py），
# 数据里的 image/gif_url 形如 "images/xxx.jpg" / "videos/xxx.gif"
MEDIA_BASE = "/media/exercises/"


def _media_url(path: str) -> str:
    if not path:
        return ""
    return MEDIA_BASE + path


@dataclass
class ExerciseOut:
    """给 LLM / 前端的精简动作结构。"""

    id: str
    name: str
    name_zh_hint: str
    category: str
    category_zh: str
    equipment: str
    equipment_zh: str
    target: str
    target_zh: str
    secondary_muscles: list[str]
    gif_url: str
    image: str
    steps_zh: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "category_zh": self.category_zh,
            "equipment": self.equipment,
            "equipment_zh": self.equipment_zh,
            "target": self.target,
            "target_zh": self.target_zh,
            "secondary_muscles": self.secondary_muscles,
            "gif_url": self.gif_url,
            "image": self.image,
            "steps_zh": self.steps_zh,
        }


def _serialize(ex: Exercise) -> dict[str, Any]:
    steps_zh = (ex.instruction_steps or {}).get("zh") or []
    # 个别动作可能没有中文步骤，回退到中文整段说明拆句
    if not steps_zh:
        zh_text = (ex.instructions or {}).get("zh") or ""
        steps_zh = [s.strip() for s in zh_text.split("。") if s.strip()]
    return ExerciseOut(
        id=ex.id,
        name=ex.name,
        name_zh_hint=ex.name,
        category=ex.category,
        category_zh=CATEGORY_ZH.get(ex.category, ex.category),
        equipment=ex.equipment,
        equipment_zh=EQUIPMENT_ZH.get(ex.equipment, ex.equipment),
        target=ex.target,
        target_zh=TARGET_ZH.get(ex.target, ex.target),
        secondary_muscles=ex.secondary_muscles or [],
        gif_url=_media_url(ex.gif_url),
        image=_media_url(ex.image),
        steps_zh=steps_zh,
    ).to_dict()


def _unsafe_for_parts(ex: Exercise, blocked_keywords: set[str]) -> bool:
    """如果动作的目标肌或协同肌命中禁忌关键词，则认为不安全。"""
    if not blocked_keywords:
        return False
    muscles = {ex.target or "", *(ex.secondary_muscles or [])}
    muscles_lower = {m.lower() for m in muscles}
    return any(kw in m for m in muscles_lower for kw in blocked_keywords)


def search_exercises(
    db: Session,
    *,
    categories: list[str] | None = None,
    equipment: list[str] | None = None,
    targets: list[str] | None = None,
    exclude_equipment: list[str] | None = None,
    contraindicated_parts: list[str] | None = None,
    keyword: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """多条件检索动作。

    参数语义：
    - categories: 仅保留这些身体部位（英文，如 ["chest","back"]）
    - equipment: 仅保留这些器械（用户"可用"的器械集合，OR 关系）
    - targets: 仅保留这些目标肌
    - exclude_equipment: 排除这些器械
    - contraindicated_parts: 禁忌/受伤部位（中英文均可，如 ["knees","腰"]）
    - keyword: 按动作名模糊搜索
    - limit: 返回上限（LLM 工具调用默认 50，避免上下文爆炸）
    """
    stmt = select(Exercise)

    if categories:
        stmt = stmt.where(Exercise.category.in_(categories))
    if targets:
        stmt = stmt.where(Exercise.target.in_(targets))
    if equipment:
        stmt = stmt.where(Exercise.equipment.in_(equipment))
    if exclude_equipment:
        stmt = stmt.where(~Exercise.equipment.in_(exclude_equipment))
    if keyword:
        stmt = stmt.where(Exercise.name.ilike(f"%{keyword}%"))

    rows = db.scalars(stmt.limit(limit * 4)).all()  # 多取一些用于禁忌过滤后补足

    # 收集禁忌关键词
    blocked: set[str] = set()
    for part in contraindicated_parts or []:
        key = part.strip().lower()
        if key in INJURY_KEYWORDS:
            blocked.update(INJURY_KEYWORDS[key])
        else:
            # 直接把用户输入当作关键词（如 "shoulder"）
            blocked.add(key)

    results: list[dict[str, Any]] = []
    for ex in rows:
        if _unsafe_for_parts(ex, blocked):
            continue
        results.append(_serialize(ex))
        if len(results) >= limit:
            break
    return results


def get_by_id(db: Session, exercise_id: str) -> dict[str, Any] | None:
    ex = db.get(Exercise, exercise_id)
    return _serialize(ex) if ex else None


def list_facets(db: Session) -> dict[str, Any]:
    """返回可选筛选维度（给前端筛选器与 LLM 了解数据范围）。"""
    categories = sorted(db.scalars(select(Exercise.category).distinct()).all())
    equipment = sorted(db.scalars(select(Exercise.equipment).distinct()).all())
    targets = sorted(db.scalars(select(Exercise.target).distinct()).all())
    return {
        "categories": [{"value": c, "label_zh": CATEGORY_ZH.get(c, c)} for c in categories],
        "equipment": [{"value": e, "label_zh": EQUIPMENT_ZH.get(e, e)} for e in equipment],
        "targets": [{"value": t, "label_zh": TARGET_ZH.get(t, t)} for t in targets],
    }


def stats(db: Session) -> dict[str, Any]:
    total = db.scalar(select(func.count()).select_from(Exercise))
    by_category = dict(
        db.execute(
            select(Exercise.category, func.count())
            .group_by(Exercise.category)
            .order_by(func.count().desc())
        ).all()
    )
    return {"total": total, "by_category": by_category}
