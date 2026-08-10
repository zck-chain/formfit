"""动作百科查询接口（公开，供 App / 后台 / 智能体检索）。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import exercise_service as svc

router = APIRouter(prefix="/api/exercises", tags=["exercises"])


@router.get("/facets")
def facets(db: Session = Depends(get_db)):
    """可选筛选维度（部位/器械/目标肌的中英文）。"""
    return svc.list_facets(db)


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    return svc.stats(db)


@router.get("")
def search(
    db: Session = Depends(get_db),
    category: list[str] | None = Query(None),
    equipment: list[str] | None = Query(None),
    target: list[str] | None = Query(None),
    keyword: str | None = None,
    injury: list[str] | None = Query(None, description="禁忌部位"),
    limit: int = Query(30, ge=1, le=100),
):
    return svc.search_exercises(
        db,
        categories=category,
        equipment=equipment,
        targets=target,
        keyword=keyword,
        contraindicated_parts=injury,
        limit=limit,
    )


@router.get("/{exercise_id}")
def detail(exercise_id: str, db: Session = Depends(get_db)):
    ex = svc.get_by_id(db, exercise_id)
    if not ex:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="动作不存在")
    return ex
