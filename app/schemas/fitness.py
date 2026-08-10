"""用户档案、评估、计划相关 Pydantic 模型。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---- 用户档案 ----
class ProfileIn(BaseModel):
    gender: str | None = Field(None, description="male/female/other")
    age: int | None = Field(None, ge=10, le=100)
    height_cm: float | None = Field(None, ge=100, le=250)
    weight_kg: float | None = Field(None, ge=30, le=300)
    goal: str | None = Field(None, description="增肌/减脂/塑形/维持/康复")
    level: str | None = Field(None, description="beginner/intermediate/advanced")
    days_per_week: int | None = Field(None, ge=1, le=7)
    available_equipment: list[str] = Field(default_factory=list)
    injury_notes: str | None = None
    contraindicated_parts: list[str] = Field(default_factory=list)


class ProfileOut(ProfileIn):
    model_config = {"from_attributes": True}


# ---- 评估 ----
class AssessmentOut(BaseModel):
    id: int
    direction: str | None
    body_type: str | None
    summary: str | None
    observed: list[str]
    safety_notes: str | None
    media_url: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


# ---- 计划 ----
class PlanGenerateIn(BaseModel):
    """触发生成计划。可选传入评估 id；不传则用用户当前档案。"""
    assessment_id: int | None = None
    goal: str | None = None
    level: str | None = None
    days_per_week: int | None = None
    available_equipment: list[str] | None = None
    contraindicated_parts: list[str] | None = None
    injury_notes: str | None = None


class PlanOut(BaseModel):
    id: int
    title: str
    goal: str | None
    level: str | None
    weeks: int
    days_per_week: int
    content: dict[str, Any]
    notes: str | None
    is_active: bool
    created_at: datetime | None

    model_config = {"from_attributes": True}


# ---- 训练记录 ----
class WorkoutSetIn(BaseModel):
    exercise_id: str
    set_index: int
    weight_kg: float | None = None
    reps: int | None = None
    done: bool = True
    rpe: float | None = None


class WorkoutLogIn(BaseModel):
    plan_id: int | None = None
    title: str = "训练"
    duration_min: int | None = None
    note: str | None = None
    workout_date: datetime | None = None
    sets: list[WorkoutSetIn] = Field(default_factory=list)


class WorkoutLogOut(BaseModel):
    id: int
    title: str
    duration_min: int | None
    note: str | None
    workout_date: datetime | None
    sets: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"from_attributes": True}
