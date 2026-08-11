# FormFit 后端生产镜像
#
# 单容器、单 worker（SQLite 硬约束，见 docs/deployment/1panel.md）。
# 构建上下文为仓库根；exercises-dataset 的 GIF/JPG 为只读静态素材，随镜像一起打包，
# 保证单镜像自包含、可复现；用户上传、数据库、备份走持久卷 /data。

FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 先装依赖，利用层缓存
COPY requirements.txt ./
RUN pip install -r requirements.txt

# 复制应用代码、迁移、运维脚本与动作数据集（只读素材）
COPY app ./app
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY exercises-dataset ./exercises-dataset

# 运行期目录：数据库、上传、备份。生产由持久卷挂载到 /data。
RUN mkdir -p /data/formfit /data/uploads /data/backups

# 容器以非 root 运行
RUN useradd -m -u 10001 appuser \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

# 容器健康检查：命中 /healthz（含数据库探活），不输出任何敏感信息。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys,urllib.request;\
req=urllib.request.Request('http://127.0.0.1:8000/healthz');\
sys.exit(0 if urllib.request.urlopen(req,timeout=4).status==200 else 1)" \
    || exit 1

# 单进程、单 worker。SQLite 不支持多 worker 并发写；要水平扩展必须先迁 PostgreSQL。
# 入口脚本负责：首次启动建表/导入动作、执行 Alembic 迁移、最后 exec uvicorn。
ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
