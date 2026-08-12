# FormFit v1 生产部署（腾讯云 1Panel + SQLite）

本文档面向运维，覆盖首次部署、HTTPS 反代、每日备份到腾讯云 COS、升级与回滚。

## 0. 适用范围与硬约束

v1 是**单实例、低容量、单人首批使用**的形态：

- 单台腾讯云服务器，1Panel 管理；
- 后端单容器、`uvicorn --workers 1`；
- SQLite 单文件库 + 每日离线备份；
- 无 Redis、无多副本、无限流共享存储。

> ⚠️ **SQLite 硬约束**：生产部署**绝不允许**多 worker（`WEB_CONCURRENCY=1`）或多副本。
> 多进程并发写会导致 `database is locked`，严重时损坏库。任何扩容需求必须先迁
> PostgreSQL 并重新评审，不要直接调大 worker 数。

## 1. 服务器准备

1. 腾讯云新建轻量/CVM，建议 2 核 2G 起步，系统 Ubuntu 22.04 / Debian 12。
2. 安全组只放行 `22`、`80`、`443`；**不要**把 8000 端口暴露到公网。
3. 安装 1Panel（按官网一键脚本），登录 1Panel 面板。
4. 在 1Panel 安装 **Docker**（应用商店 → Docker）。

## 2. 获取代码与配置

```bash
# 在服务器上拉取代码（用发布 tag）
git clone https://github.com/zck-chain/formfit.git /opt/formfit
cd /opt/formfit
git checkout <release-tag>

# 准备生产环境变量
cp .env.example .env
```

编辑 `.env`，**至少**改这些（其余可保留默认）：

```ini
APP_ENV=production

# 用 openssl rand -hex 32 生成，三者必须互不相同
JWT_SECRET=<随机64位hex>
ADMIN_SESSION_SECRET=<随机64位hex，不同于JWT_SECRET>

# 管理员后台首登强密码（≥8位，绝不能用默认值）
ADMIN_EMAIL=admin@your-domain.com
ADMIN_PASSWORD=<强密码>

# 允许的跨域来源（App/后台域名），逗号分隔；留空则仅同源
CORS_ORIGINS=https://app.your-domain.com

# v1 不接真实支付凭证前，保持为空；真实凭证就绪前不得包含 sandbox
PAYMENT_CHANNELS=

# 反向代理之后，可信代理会覆写 XFF，开启后按 XFF 首 IP 限流
TRUSTED_PROXY_ENABLED=true

# DeepSeek / 通义千问真实 key（无 key 时 AI 返回保底结果）
DEEPSEEK_API_KEY=<真实key>
DASHSCOPE_API_KEY=<真实key>

LOG_LEVEL=INFO
WEB_CONCURRENCY=1
```

> 启动时若仍用默认密钥/弱密码、或 `PAYMENT_CHANNELS` 含 `sandbox`、或
> `WEB_CONCURRENCY>1`、或用了内存库，应用会 **fail-fast 直接拒绝启动**，
> 错误信息打印在容器日志里。

生成随机串：

```bash
openssl rand -hex 32   # 跑两次，分别给 JWT_SECRET 与 ADMIN_SESSION_SECRET
```

## 3. 启动容器

在 1Panel 中用「容器 → 编排 → 创建 Compose」，把 `docker-compose.yml` 内容粘进去
（或在 `/opt/formfit` 下执行）：

```bash
docker compose --env-file .env up -d --build
```

三个具名卷会自动创建，分别持久化：

| 卷 | 容器路径 | 内容 |
|---|---|---|
| `formfit_formfit-db` | `/data/formfit` | `formfit.db`（SQLite 主库 + WAL） |
| `formfit_formfit-uploads` | `/data/uploads` | 用户体态评估照片（隐私） |
| `formfit_formfit-backups` | `/data/backups` | 每日 SQLite 快照 |

> 用户上传与数据库分卷存放，备份策略不同：数据库每日快照，上传目录由
> 1Panel「文件备份/快照」按主机卷定期备份即可。

验证：

```bash
# 容器状态应为 healthy
docker ps --filter name=formfit

# 健康检查（容器内）
curl -fsS http://127.0.0.1:8000/healthz   # 期望 {"status":"ok"}

# 看启动日志（JSON 结构化输出到 stdout）
docker logs -f formfit
```

`/healthz` 会执行一条 `SELECT 1` 探活数据库；数据库异常返回 503，编排会据此重启。
响应体只含 `status`/`reason`，不含路径、连接串或密钥。

首次启动 entrypoint 会自动：执行 Alembic 迁移 → 在动作表为空时导入 1324 个动作。

## 4. 反向代理与 HTTPS

在 1Panel 创建「网站 → 反向代理」：

- 主域名 `api.your-domain.com`，代理到 `http://127.0.0.1:8000`；
- 申请 Let's Encrypt 证书并开启**自动续期**（1Panel 自带定时任务）；
- 强制 HTTPS、开启 HTTP/2。

建议在反代层加上：

- 客户端真实 IP 透传：`X-Forwarded-For`、`X-Forwarded-Proto`（1Panel 反代默认带）；
- 上传体积限制：与应用 `UPLOAD_MAX_BYTES`（默认 10MB）保持一致，反代设 `client_max_body_size 12m`；
- `/healthz` 可放开给本机/内网探针，不必走公网。

后端启动参数带 `--proxy-headers`，会正确识别反代注入的 `X-Forwarded-Proto`。

> 上述是「`api` 子域名只代理后端」的形态。若要把 Flutter Web/PWA 与后端部署在
> **同一域名**（`/api`、`/media`、`/static` 反代后端，其余路径托管 `build/web`，
> SPA 深链刷新不 404），使用仓库 `deploy/nginx/formfit-web.conf`，构建/发布/回滚
> 步骤见 [`web-release.md`](./web-release.md)。两者二选一，不要把 80/443 同时配给
> 两套 server 块。

## 5. 每日备份与腾讯云 COS

### 5.1 数据库快照（应用一致性）

在 1Panel「计划任务」新增 Shell 脚本，每天凌晨（如 03:20）执行：

```bash
cd /opt/formfit
docker compose exec -T formfit python -m app.ops.backup \
  --db /data/formfit/formfit.db \
  --out /data/backups \
  --retain-days 14
```

或直接用宿主机封装脚本：

```bash
/opt/formfit/scripts/backup_sqlite.sh
```

脚本特性：

- 用 SQLite **在线备份 API**（等价 `sqlite3 .backup`）逐页拷贝，**绝不裸 cp** 正在写入的库；
- 快照后自动 `PRAGMA integrity_check` + 校验核心表存在，失败删除快照并返回非零；
- 为每个快照写 `<name>.sha256`，恢复前校验；
- 默认保留 **14 天**，超期快照及其校验文件一并清理；
- 备份失败退出码非 0，1Panel 会按计划任务配置发邮件告警。

> 脚本**不**包含任何腾讯云 COS 密钥，也**不**直接上传。

### 5.2 上传到 COS

用 1Panel 自带能力之一即可，不要把 COS 密钥写进应用或脚本：

- 「计划任务 → 备份到对象存储」，把宿主机的 Docker 卷目录
  `/var/lib/docker/volumes/formfit_formfit-backups/_data` 同步到 COS 存储桶；
- 或在 1Panel「容器 → 备份」配置卷备份到 COS。

建议开启 COS 版本控制与服务端加密，并保留与本地一致的周期。

### 5.3 上传目录备份

`/var/lib/docker/volumes/formfit_formfit-uploads/_data` 用 1Panel「文件保护/快照」
按周备份即可（用户照片体积大、变更频率低）。

## 6. 恢复演练（必须先在临时副本做）

> ⚠️ 恢复脚本**默认拒绝覆盖**已存在的目标。严禁把 `--target` 指向正在使用的生产库。

```bash
# 1) 在容器内把最近快照恢复到一个临时文件
LATEST=$(ls -1 /data/backups/formfit-*.db | tail -1)
docker compose exec formfit python -m app.ops.restore \
  --snapshot "$LATEST" \
  --target /data/backups/restore-drill.db

# 输出每张关键表的行数，人工核对与线上一致：
#   restored=/data/backups/restore-drill.db
#   count users=..
#   count orders=..
#   ...

# 2) 演练完成删除临时库
docker compose exec formfit rm -f /data/backups/restore-drill.db
```

真正需要恢复生产时（停机窗口内）：

```bash
# 先停应用，避免恢复期间有新写入
docker compose stop formfit

# 把当前损坏的库挪走（不要直接删）
docker run --rm -v formfit_formfit-db:/data busybox \
  mv /data/formfit.db /data/formfit.db.broken

# 恢复（目标是新文件，用 --force 仅在目标已存在且确认无用时）
docker compose run --rm formfit python -m app.ops.restore \
  --snapshot /data/backups/formfit-YYYYMMDD-HHMMSS.db \
  --target /data/formfit/formfit.db

docker compose up -d formfit
curl -fsS http://127.0.0.1:8000/healthz
```

## 7. 升级

```bash
cd /opt/formfit
git fetch --tags
git checkout <new-tag>

# 构建新镜像并启动（entrypoint 自动跑迁移；动作表非空不重复导入）
docker compose --env-file .env up -d --build

docker logs -f formfit           # 确认迁移与启动正常
curl -fsS http://127.0.0.1:8000/healthz
```

升级前建议先手动打一份快照：

```bash
docker compose exec -T formfit python -m app.ops.backup \
  --db /data/formfit/formfit.db --out /data/backups --retain-days 14
```

## 8. 回滚

```bash
cd /opt/formfit
git checkout <previous-tag>
docker compose --env-file .env up -d --build
```

数据卷不动，回退镜像版本后挂载的仍是同一份数据。若新版本的迁移需要回退 schema，
先在停机窗口用 `alembic downgrade <revision>` 回退，再回滚镜像——日常升级尽量保持
向后兼容的迁移以简化回滚。

## 9. 日志与监控

- 应用日志为 JSON，输出到 `stdout/stderr`，由 Docker 接管；
- 在 1Panel 可直接查看容器日志，或配置「容器日志」采集；Docker 默认按 json-file
  驱动轮转，建议在 `/etc/docker/daemon.json` 配置 `max-size`/`max-file`（如 10m×5）；
- 关键日志字段：`time`、`level`、`event`、`request_id`、`method`、`path`、
  `status`、`duration_ms`、`client_ip`；
- **不记录** JWT、Cookie/会话、密钥、完整支付回调体、用户照片；支付回调仅记录
  `channel` 与错误摘要。

主要监控信号：

- 容器健康检查（`/healthz` 非 200 → 重启/告警）；
- 备份计划任务退出码非 0（1Panel 邮件告警）；
- 磁盘水位（SQLite + 上传 + 快照都在本机卷，预留 ≥20% 空闲）。

## 10. 未覆盖 / 发布前人工门禁

- 真实支付宝/微信商户凭证接入与沙箱回调联调；
- 真实 DeepSeek / DashScope key 与 AI 输出质量评审；
- 域名备案与 Android 真机；
- 容量增长后迁 PostgreSQL + Redis（共享限流）的评审窗口。
