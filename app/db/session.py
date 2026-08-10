"""SQLAlchemy 引擎与会话。默认 SQLite，切换 PostgreSQL 只需改 DATABASE_URL。"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

# SQLite 需要 check_same_thread=False 以配合 FastAPI 多线程
connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个数据库会话，请求结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
