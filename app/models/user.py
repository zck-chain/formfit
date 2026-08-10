"""用户、档案、会员、评估、计划、训练记录。"""
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 角色：user（App 用户）/ admin（Web 后台）
    role: Mapped[str] = mapped_column(String(16), default="user", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    membership: Mapped["Membership | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class UserProfile(Base):
    """用户身体数据与训练偏好。可随评估更新。"""

    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)

    gender: Mapped[str | None] = mapped_column(String(16))          # male / female / other
    age: Mapped[int | None] = mapped_column(Integer)
    height_cm: Mapped[float | None] = mapped_column(Float)
    weight_kg: Mapped[float | None] = mapped_column(Float)

    # 训练偏好
    goal: Mapped[str | None] = mapped_column(String(32))            # 增肌/减脂/塑形/维持/康复
    level: Mapped[str | None] = mapped_column(String(16))           # beginner/intermediate/advanced
    days_per_week: Mapped[int | None] = mapped_column(Integer)
    available_equipment: Mapped[list] = mapped_column(JSON, default=list)  # 可用器械
    injury_notes: Mapped[str | None] = mapped_column(Text)          # 伤病史/禁忌自由文本
    contraindicated_parts: Mapped[list] = mapped_column(JSON, default=list)  # 禁忌部位，如 ["knees","lower back"]

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="profile")


class Membership(Base):
    """会员订阅状态。支付接口预留：order 相关字段先存着，不接支付。"""

    __tablename__ = "memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)

    plan: Mapped[str] = mapped_column(String(32), default="free")   # free / pro
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # 支付预留（order_id 存订单号 order_no）
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payment_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 渠道侧订阅/交易原始 ID：用于 IAP 恢复购买（如 Apple original_transaction_id）
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(191), nullable=True, unique=True
    )

    user: Mapped["User"] = relationship(back_populates="membership")


class BodyAssessment(Base):
    """一次拍照/视频评估记录。"""

    __tablename__ = "body_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    media_path: Mapped[str] = mapped_column(String(512))            # 上传的图片/视频路径
    media_type: Mapped[str] = mapped_column(String(16))             # image / video

    # AI 评估结果
    direction: Mapped[str | None] = mapped_column(String(32))       # gain(增肌)/fat_loss(减脂)/rehab(康复提示)
    body_type: Mapped[str | None] = mapped_column(String(64))       # 体型/体态判断
    summary: Mapped[str | None] = mapped_column(Text)               # 自然语言总结
    raw_result: Mapped[dict] = mapped_column(JSON, default=dict)    # 模型原始返回

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Plan(Base):
    """一次生成的训练计划。结构以 JSON 保存，灵活且可直接回显。"""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    title: Mapped[str] = mapped_column(String(255))
    goal: Mapped[str | None] = mapped_column(String(32), index=True)
    level: Mapped[str | None] = mapped_column(String(16))
    weeks: Mapped[int] = mapped_column(Integer, default=4)
    days_per_week: Mapped[int] = mapped_column(Integer, default=3)

    # 完整计划结构：[{"day": "周一 推日", "items": [{"exercise_id":..., "sets":..., "reps":...}, ...]}, ...]
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)

    source: Mapped[str] = mapped_column(String(32), default="ai")  # ai / custom
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WorkoutLog(Base):
    """一次实际训练（某天完成的训练会话）。"""

    __tablename__ = "workout_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"), nullable=True)

    title: Mapped[str] = mapped_column(String(255), default="训练")
    workout_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    duration_min: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)

    sets: Mapped[list["WorkoutSet"]] = relationship(
        back_populates="log", cascade="all, delete-orphan"
    )


class WorkoutSet(Base):
    """一组记录：某个动作、第几组、重量、次数、是否完成。"""

    __tablename__ = "workout_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    log_id: Mapped[int] = mapped_column(ForeignKey("workout_logs.id"), index=True)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id"), index=True)

    set_index: Mapped[int] = mapped_column(Integer)        # 第几组
    weight_kg: Mapped[float | None] = mapped_column(Float)
    reps: Mapped[int | None] = mapped_column(Integer)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    rpe: Mapped[float | None] = mapped_column(Float)       # 主观疲劳度，选填

    log: Mapped["WorkoutLog"] = relationship(back_populates="sets")
