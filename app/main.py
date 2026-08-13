"""FormFit 后端入口。"""
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.routes import admin, auth, exercises, fitness, membership, payment
from app.core.config import BASE_DIR, DATASET_DIR, settings
from app.core.health import router as health_router
from app.core.logging_config import configure_logging, request_id_ctx
from app.core.rate_limit import limiter
from app.models import *  # noqa: F401,F403  确保所有模型注册到 Base.metadata
from app.startup import init_admin, init_db

# 结构化日志（JSON 到 stdout，由 Docker/1Panel 采集与轮转）。
configure_logging(settings.log_level)
logger = logging.getLogger("formfit")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_admin()
    yield


app = FastAPI(
    title="FormFit API",
    description="AI 健身私教后端：体态评估、计划生成、动作百科、训练记录",
    version="0.1.0",
    lifespan=lifespan,
)

# 限流：注册到 app，各路由用 @limiter.limit(...) 声明阈值
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# 介绍作品页（落地页）模板，与后台 Jinja2 模板目录同源。
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@app.middleware("http")
async def request_id_and_access_log(request: Request, call_next):
    """为每个请求分配/透传 request_id，并输出一条结构化访问日志。

    - 优先采信反向代理注入的 X-Request-ID，否则生成短随机 id。
    - 访问日志只记方法/路径/状态/耗时/客户端 IP，不记录 Authorization/Cookie、
      请求体或查询串中的敏感参数。
    """
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    token = request_id_ctx.set(rid)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = rid
        # 健康检查噪音太大，不打访问日志；其余请求记录一行。
        if request.url.path != "/healthz":
            logger.info(
                "%s %s -> %s",
                request.method,
                request.url.path,
                response.status_code,
                extra={
                    "event": "http_request",
                    "request_id": rid,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                    "client_ip": request.client.host if request.client else None,
                },
            )
        return response
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.exception(
            "request failed",
            extra={
                "event": "request_error",
                "request_id": rid,
                "method": request.method,
                "path": request.url.path,
                "duration_ms": round(duration_ms, 2),
                "client_ip": request.client.host if request.client else None,
            },
        )
        raise
    finally:
        request_id_ctx.reset(token)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request, exc):
    from fastapi.responses import JSONResponse

    # slowapi 的异常详情转成统一 429
    return JSONResponse(
        status_code=429,
        content={"detail": "请求过于频繁，请稍后再试"},
        headers={"Retry-After": str(int(exc.limit.limit.get_expiry()))},
    )


# CORS：从配置读取来源白名单。生产绝不使用 allow_origins=["*"] + credentials。
cors_origins = settings.effective_cors_origins()
if settings.is_production and not cors_origins:
    logger.info("生产环境未配置 CORS_ORIGINS，仅允许同源请求（不放开跨域）")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-CSRF-Token"],
)
logger.info("CORS 允许来源：%s", cors_origins or "(仅同源)")

# API 路由
app.include_router(health_router)
app.include_router(auth.router)
app.include_router(exercises.router)
app.include_router(fitness.router)
app.include_router(admin.router)
app.include_router(payment.router)
app.include_router(membership.router)

# 用户上传：独立挂载到 /static/uploads，目录由 UPLOAD_DIR 决定，
# 这样在生产可把它指向持久卷（如 /data/uploads），而不必把整个 app/static 挂出去。
# 必须先于下面的 /static 挂载，使更具体的前缀优先生效。
app.mount(
    "/static/uploads",
    StaticFiles(directory=settings.upload_dir),
    name="uploads",
)

# 静态资源：后台 CSS/JS（位于 app/static 下）
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


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    """公开介绍作品页（落地页）：产品亮点、动作库展示、下载与联系方式。

    下载链接与联系方式由运行时配置注入，未配置时按钮显示「即将开放」。
    """
    return templates.TemplateResponse(
        request,
        "landing.html",
        {
            "android_download_url": settings.landing_android_download_url,
            "contact_email": settings.landing_contact_email,
            "contact_wechat": settings.landing_contact_wechat,
        },
    )


@app.get("/api")
def api_index():
    # 接口发现入口（原根路径 JSON 信息迁移至此，供联调/探活参考）。
    return {
        "app": settings.app_name,
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "auth": "/api/auth",
            "exercises": "/api/exercises",
            "fitness": "/api/fitness",
            "membership": "/api/membership",
            "payment": "/api/payment",
            "health": "/healthz",
        },
    }


@app.get("/health")
def health():
    # 兼容旧探针；新部署请用 /healthz（含数据库探活）
    return {"status": "ok"}
