"""FormFit 后端入口。"""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import admin, auth, exercises, fitness
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


def _build_cors_origins() -> list[str]:
    """根据配置决定 CORS 允许来源。

    - 生产：必须显式白名单，不允许 "*"（validate_production 已在启动时把关）。
    - 开发：未配置时回退到 "*"，但此时必须关闭 credentials，
      避免浏览器规范禁止的 "*" + credentials 组合。
    """
    origins = settings.cors_origin_list
    if origins:
        # 显式白名单：任何环境都安全（含 credentials）
        return origins
    if settings.is_production:
        # 生产缺白名单不应到这里——validate_production 会先拒绝启动；
        # 兜底返回空列表，拒绝所有跨域。
        logger.error("生产环境未配置 cors_origins，CORS 已禁用")
        return []
    # 开发环境且未配置：放开来源，但强制关闭 credentials。
    return ["*"]


_cors_origins = _build_cors_origins()
# credentials 仅在有显式白名单（非空、非通配）时才有意义；
# "*" 或空白名单都必须关闭，杜绝 *+credentials，也避免空配置带凭证。
_effective_credentials = bool(
    settings.cors_allow_credentials and _cors_origins and "*" not in _cors_origins
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # "*" 与 credentials 不能同时为 True（浏览器会拒绝，也是 WS-2 指出的风险）。
    allow_credentials=_effective_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# API 路由
app.include_router(auth.router)
app.include_router(exercises.router)
app.include_router(fitness.router)
app.include_router(admin.router)

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
    # 生产环境安全门禁：占位密钥/弱配置直接拒绝启动。
    settings.validate_production()
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
        },
    }


@app.get("/health")
def health():
    return {"status": "ok"}
