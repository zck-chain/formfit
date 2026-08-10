"""把 exercises-dataset/data/exercises.json 导入数据库。

用法：
    python -m scripts.seed_exercises            # 首次导入
    python -m scripts.seed_exercises --reset    # 清空动作表后重新导入
"""
import argparse
import json
import sys
from pathlib import Path

# 让脚本在项目根目录下可直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import EXERCISES_JSON  # noqa: E402
from app.db.session import Base, SessionLocal, engine  # noqa: E402
from app.models import Exercise  # noqa: E402,F401  (确保模型已注册)


def parse_created_at(value: str | None):
    if not value:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def load_exercises() -> list[dict]:
    if not EXERCISES_JSON.exists():
        raise FileNotFoundError(f"找不到数据集：{EXERCISES_JSON}")
    with open(EXERCISES_JSON, encoding="utf-8") as f:
        return json.load(f)


def main(reset: bool) -> None:
    Base.metadata.create_all(bind=engine)
    data = load_exercises()

    db = SessionLocal()
    try:
        if reset:
            deleted = db.query(Exercise).delete()
            db.commit()
            print(f"已清空旧动作 {deleted} 条")

        existing = {eid for eid, in db.query(Exercise.id).all()}
        added = 0
        skipped = 0
        for item in data:
            if item["id"] in existing:
                skipped += 1
                continue
            db.add(
                Exercise(
                    id=item["id"],
                    name=item["name"],
                    category=item.get("category") or item.get("body_part"),
                    equipment=item.get("equipment", ""),
                    target=item.get("target", ""),
                    muscle_group=item.get("muscle_group"),
                    secondary_muscles=item.get("secondary_muscles", []),
                    instructions=item.get("instructions", {}),
                    instruction_steps=item.get("instruction_steps", {}),
                    image=item.get("image", ""),
                    gif_url=item.get("gif_url", ""),
                    media_id=item.get("media_id"),
                    attribution=item.get("attribution"),
                    is_custom=False,
                    created_at=parse_created_at(item.get("created_at")),
                )
            )
            added += 1
        db.commit()
        total = db.query(Exercise).count()
        print(f"导入完成：新增 {added}，跳过已存在 {skipped}，当前共 {total} 个动作")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="先清空动作表再导入")
    args = parser.parse_args()
    main(reset=args.reset)
