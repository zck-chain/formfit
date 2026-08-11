"""评估、档案、计划生成、训练记录接口（需登录）。"""
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import planner, qwen_vl_client
from app.api.deps import get_current_user, require_pro_membership
from app.core.config import settings
from app.core.rate_limit import limiter, user_or_ip_key
from app.db.session import get_db
from app.models import (
    BodyAssessment,
    Plan,
    User,
    UserProfile,
    WorkoutLog,
    WorkoutSet,
)
from app.schemas.fitness import (
    PlanGenerateIn,
    PlanOut,
    ProfileIn,
    ProfileOut,
    WorkoutLogIn,
    WorkoutLogOut,
)
from app.utils.images import ImageValidationError, validate_and_prepare

router = APIRouter(prefix="/api/fitness", tags=["fitness"])

# 仅作为客户端声明的快速过滤；真实类型以 magic bytes/Pillow 校验为准
DECLARED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


# ---------- 用户档案 ----------
def _get_or_create_profile(db: Session, user: User) -> UserProfile:
    profile = user.profile
    if not profile:
        profile = UserProfile(user_id=user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@router.get("/profile", response_model=ProfileOut)
def get_profile(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _get_or_create_profile(db, user)


@router.put("/profile", response_model=ProfileOut)
def update_profile(
    body: ProfileIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    profile = _get_or_create_profile(db, user)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile


# ---------- 体态拍照评估 ----------
@router.post(
    "/assess",
    dependencies=[Depends(require_pro_membership("assess"))],
)
@limiter.limit(settings.rate_limit_assess, key_func=user_or_ip_key)
async def assess_body(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    file: UploadFile = File(...),
    height_cm: float | None = Form(None),
    weight_kg: float | None = Form(None),
    age: int | None = Form(None),
    gender: str | None = Form(None),
):
    # 1) 客户端声明的 content_type 快速过滤（真实类型下面用 Pillow 校验）
    if file.content_type and file.content_type not in DECLARED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 JPG/PNG/WebP/HEIC 图片")

    # 2) 读取并限制大小（StreamingFiles 不预先知道大小，这里一次性读入内存）
    raw = await file.read()
    try:
        data, ext, mime = validate_and_prepare(raw, file.content_type)
    except ImageValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    # 3) 落盘（隐私路径：用户id + 随机名，不保留原始文件名）
    save_name = f"{user.id}_{uuid.uuid4().hex}{ext}"
    save_path = settings.upload_dir / save_name
    save_path.write_bytes(data)

    # 若表单带了身体数据，顺手更新档案
    profile = _get_or_create_profile(db, user)
    if height_cm:
        profile.height_cm = height_cm
    if weight_kg:
        profile.weight_kg = weight_kg
    if age:
        profile.age = age
    if gender:
        profile.gender = gender
    db.commit()

    result = await qwen_vl_client.assess_body(
        save_path,
        height_cm=profile.height_cm,
        weight_kg=profile.weight_kg,
        age=profile.age,
        gender=profile.gender,
    )

    record = BodyAssessment(
        user_id=user.id,
        media_path=f"uploads/{save_name}",
        media_type="image",
        direction=result.get("direction"),
        body_type=result.get("body_type"),
        summary=result.get("summary"),
        raw_result=result,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "id": record.id,
        "direction": record.direction,
        "body_type": record.body_type,
        "summary": record.summary,
        "observed": result.get("observed", []),
        "safety_notes": result.get("safety_notes"),
        "media_url": f"/static/{record.media_path}",
        "created_at": record.created_at,
    }


# ---------- 计划生成 ----------
@router.post(
    "/plans/generate",
    response_model=PlanOut,
    dependencies=[Depends(require_pro_membership("generate_plan"))],
)
@limiter.limit(settings.rate_limit_generate_plan, key_func=user_or_ip_key)
async def generate_plan(
    request: Request,
    body: PlanGenerateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    profile = _get_or_create_profile(db, user)

    # 请求中临时覆盖的字段（不改档案）
    profile_dict = {
        "gender": profile.gender,
        "age": profile.age,
        "height_cm": profile.height_cm,
        "weight_kg": profile.weight_kg,
        "goal": body.goal or profile.goal,
        "level": body.level or profile.level,
        "days_per_week": body.days_per_week or profile.days_per_week or 3,
        "available_equipment": body.available_equipment
        or profile.available_equipment
        or ["body weight"],
        "contraindicated_parts": body.contraindicated_parts
        if body.contraindicated_parts is not None
        else profile.contraindicated_parts,
        "injury_notes": body.injury_notes
        if body.injury_notes is not None
        else profile.injury_notes,
    }

    assessment = None
    if body.assessment_id:
        assessment = db.get(BodyAssessment, body.assessment_id)
        if assessment and assessment.user_id == user.id:
            assessment = assessment.raw_result

    # 把旧的活跃计划标记为非活跃（保留历史）
    db.query(Plan).filter(Plan.user_id == user.id, Plan.is_active.is_(True)).update(
        {"is_active": False}
    )

    plan_data = await planner.generate_plan(db, profile_dict, assessment)
    plan = Plan(
        user_id=user.id,
        title=plan_data.get("title", "我的训练计划"),
        goal=plan_data.get("goal"),
        level=profile_dict["level"],
        weeks=plan_data.get("weeks", 4),
        days_per_week=plan_data.get("days_per_week", profile_dict["days_per_week"]),
        content=plan_data,
        notes=plan_data.get("notes"),
        source="ai",
        is_active=True,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/plans", response_model=list[PlanOut])
def list_plans(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(
        select(Plan).where(Plan.user_id == user.id).order_by(Plan.created_at.desc())
    ).all()


@router.get("/plans/{plan_id}", response_model=PlanOut)
def get_plan(plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    plan = db.get(Plan, plan_id)
    if not plan or plan.user_id != user.id:
        raise HTTPException(status_code=404, detail="计划不存在")
    return plan


# ---------- 训练记录 ----------
@router.post("/logs", response_model=WorkoutLogOut)
def create_log(
    body: WorkoutLogIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    log = WorkoutLog(
        user_id=user.id,
        plan_id=body.plan_id,
        title=body.title,
        duration_min=body.duration_min,
        note=body.note,
        workout_date=body.workout_date,
    )
    db.add(log)
    db.flush()
    for s in body.sets:
        db.add(
            WorkoutSet(
                log_id=log.id,
                exercise_id=s.exercise_id,
                set_index=s.set_index,
                weight_kg=s.weight_kg,
                reps=s.reps,
                done=s.done,
                rpe=s.rpe,
            )
        )
    db.commit()
    db.refresh(log)
    return _serialize_log(log)


@router.get("/logs", response_model=list[WorkoutLogOut])
def list_logs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    logs = db.scalars(
        select(WorkoutLog)
        .where(WorkoutLog.user_id == user.id)
        .order_by(WorkoutLog.workout_date.desc())
        .limit(100)
    ).all()
    return [_serialize_log(log) for log in logs]


def _serialize_log(log: WorkoutLog) -> dict:
    return {
        "id": log.id,
        "title": log.title,
        "duration_min": log.duration_min,
        "note": log.note,
        "workout_date": log.workout_date,
        "sets": [
            {
                "exercise_id": s.exercise_id,
                "set_index": s.set_index,
                "weight_kg": s.weight_kg,
                "reps": s.reps,
                "done": s.done,
                "rpe": s.rpe,
            }
            for s in log.sets
        ],
    }
