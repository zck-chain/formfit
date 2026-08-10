"""后台数据统计服务：把运营数据整理成看板需要的结构。"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BodyAssessment,
    Exercise,
    Membership,
    Plan,
    User,
    WorkoutLog,
)


def overview(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    last_7 = now - timedelta(days=7)
    last_30 = now - timedelta(days=30)

    total_users = db.scalar(select(func.count()).select_from(User)) or 0
    new_users_7 = db.scalar(
        select(func.count()).select_from(User).where(User.created_at >= last_7)
    ) or 0
    new_users_30 = db.scalar(
        select(func.count()).select_from(User).where(User.created_at >= last_30)
    ) or 0

    pro_users = db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.is_active.is_(True), Membership.plan == "pro")
    ) or 0

    total_plans = db.scalar(select(func.count()).select_from(Plan)) or 0
    total_assessments = db.scalar(select(func.count()).select_from(BodyAssessment)) or 0
    total_logs = db.scalar(select(func.count()).select_from(WorkoutLog)) or 0
    total_exercises = db.scalar(select(func.count()).select_from(Exercise)) or 0
    custom_exercises = db.scalar(
        select(func.count()).select_from(Exercise).where(Exercise.is_custom.is_(True))
    ) or 0

    # 近 14 天每日新增用户（用于趋势小图）
    daily = []
    for i in range(13, -1, -1):
        day_start = (now - timedelta(days=i)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        day_end = day_start + timedelta(days=1)
        cnt = db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.created_at >= day_start, User.created_at < day_end)
        ) or 0
        daily.append({"date": day_start.strftime("%m-%d"), "count": cnt})

    # 评估方向分布
    direction_rows = db.execute(
        select(BodyAssessment.direction, func.count())
        .where(BodyAssessment.direction.is_not(None))
        .group_by(BodyAssessment.direction)
    ).all()

    return {
        "kpis": {
            "total_users": total_users,
            "new_users_7": new_users_7,
            "new_users_30": new_users_30,
            "pro_users": pro_users,
            "conversion_rate": round(pro_users / total_users * 100, 1) if total_users else 0,
            "total_plans": total_plans,
            "total_assessments": total_assessments,
            "total_logs": total_logs,
            "total_exercises": total_exercises,
            "custom_exercises": custom_exercises,
        },
        "daily_signups": daily,
        "directions": [{"direction": d or "未知", "count": c} for d, c in direction_rows],
    }
