"""FormFit 后端入口。"""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import admin, auth, exercises, fitness, membership, payment
from app.core.config import BASE_DIR, DATASET_DIR, settings
from app.db.session import Base, engine
from app.models import *  # noqa: F401,F403  确保所有模型注册到 Base.metadata
from app.startup import init_admin, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="FormFit API",
    description="AI 健身私教后端：体态评估、计划生成、动作百科、训练记录",
    version="0.1.0",
)

# App / 后台跨域（开发期放开；生产应收紧）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 路由
app.include_router(auth.router)
app.include_router(exercises.router)
app.include_router(fitness.router)
app.include_router(admin.router)
app.include_router(payment.router)
app.include_router(membership.router)

# 静态资源：后台 CSS/JS，以及用户上传（位于 app/static 下）
_STATIC_DIR = BASE_DIR / "app" / "static"
app.mount(
    "/static",
    StaticFiles(directory=_STATIC_DIR),
    name="static",
)
# 数据集自带的图片/动图（只读挂载，供前端直接 <img src>）
# 挂到 /media 下，避免与 /static（app 自带静态资源）的 StaticFiles 路由冲突
_dataset_images = DATASET_DIR / "images"
_dataset_videos = DATASET_DIR / "videos"
if _dataset_images.exists():
    app.mount(
        "/media/exercises/images",
        StaticFiles(directory=_dataset_images),
        name="exercise-images",
    )
if _dataset_videos.exists():
    app.mount(
        "/media/exercises/videos",
        StaticFiles(directory=_dataset_videos),
        name="exercise-videos",
    )


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    init_admin()


@app.get("/")
def root():
    return {
        "app": settings.app_name,
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "auth": "/api/auth",
            "exercises": "/api/exercises",
            "fitness": "/api/fitness",
            "payment": "/api/payment",
            "membership": "/api/membership",
        },
    }


@app.get("/health")
def health():
    return {"status": "ok"}
