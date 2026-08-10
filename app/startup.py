"""启动初始化：建表、创建默认管理员。"""
import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import Base, SessionLocal, engine
from app.models import *  # noqa: F401,F403
from app.models import Membership, User

logger = logging.getLogger(__name__)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表已就绪")


def init_admin() -> None:
    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.email == settings.admin_email))
        if existing:
            return
        admin = User(
            email=settings.admin_email,
            hashed_password=hash_password(settings.admin_password),
            nickname="管理员",
            role="admin",
        )
        db.add(admin)
        db.flush()
        db.add(Membership(user_id=admin.id, plan="pro", is_active=True))
        db.commit()
        logger.info("已创建默认管理员：%s", settings.admin_email)
    finally:
        db.close()
