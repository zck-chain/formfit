"""健身动作：来自 exercises-dataset 的 1324 个动作。

仅做只读数据底座（后台可管理）。多语言 instructions 以 JSON 存储；
常用的检索维度（category / equipment / target / secondary_muscles）建索引。
"""
from datetime import datetime

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Exercise(Base):
    __tablename__ = "exercises"

    # 数据集中的字符串 id（如 "0001"），作主键
    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)       # 身体部位，等同 body_part
    equipment: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str] = mapped_column(String(64), index=True)         # 主目标肌
    muscle_group: Mapped[str | None] = mapped_column(String(64))
    secondary_muscles: Mapped[list] = mapped_column(JSON, default=list)

    # 多语言说明：{"en": "...", "zh": [...]}  步骤数组在 instruction_steps
    instructions: Mapped[dict] = mapped_column(JSON, default=dict)
    instruction_steps: Mapped[dict] = mapped_column(JSON, default=dict)

    image: Mapped[str] = mapped_column(String(255))    # 缩略图相对路径
    gif_url: Mapped[str] = mapped_column(String(255))  # 动画 GIF 相对路径
    media_id: Mapped[str | None] = mapped_column(String(32))
    attribution: Mapped[str | None] = mapped_column(Text, default=None)

    # 后台自定义动作标记（数据集自带的为 False）
    is_custom: Mapped[bool] = mapped_column(default=False, index=True)

    created_at: Mapped[datetime | None] = mapped_column(nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Exercise {self.id} {self.name}>"
