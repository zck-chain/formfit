# 落地页根路径与 /api 发现迁移：合并与部署顺序

本说明配合 [ADR 0001](../../docs/adr/0001-landing-page-root-and-api-discovery.md)，用于 WS-52 合并判断与上线执行，明确 PR #17 与 PR #18 的先后顺序，避免 `/` 在线上短暂返回旧 JSON 或半成品入口。

## 涉及变更

- **PR #17（`feat/landing-page`，后端落地页）**
  - `GET /` 由 FastAPI/Jinja2 渲染 HTML 落地页；
  - `GET /api` 承接原根路径 JSON 接口发现；
  - 新增 `app/templates/landing.html`、`app/static/css/landing.css`、`tests/test_landing_page.py`，以及 `LANDING_*` 配置项。
- **PR #18（`chore/nginx-landing-proxy`，Nginx 精确反代）**
  - `deploy/nginx/formfit-web.conf` 新增 `location = /` 与 `location = /api`，均反代到后端；
  - 不改动上游、TLS、安全头、缓存与上传策略。

## 正确顺序（必须严格遵守）

1. **先合并并部署 PR #17（后端）。**
   - 合并后发布后端镜像 / 重启服务，使后端同时具备 `GET /`(HTML) 与 `GET /api`(JSON)。
   - 此时 Nginx 仍为旧配置：公网 `/` 由 Flutter Web 产物提供，`/api`（无尾斜杠）落入 SPA fallback。这是可接受的中间态——后端能力已就位，但尚未经 Nginx 暴露。
2. **再合并并发布 PR #18（Nginx）。**
   - 上线 `location = /`、`location = /api`；
   - 执行 `nginx -t`，通过后 `nginx -s reload`；
   - 此时公网 `/` 变为后端落地页，`/api` 返回 JSON 接口发现。

### 为什么不能颠倒

- 若先上 PR #18、后端还停在旧版本：`location = /` 会把根路径反代到旧后端，旧后端 `GET /` 仍返回 JSON（公网根路径直接暴露接口 JSON）；`location = /api` 反代到一个不存在 `/api` 路由的旧后端，返回 404。
- 先上后端（PR #17）再切 Nginx（PR #18），则任意时刻都不会出现“Nginx 把流量导向一个尚未就绪的后端路由”的空窗。

## 合并前检查

- 确认监控、巡检、上线/探活脚本没有依赖 `GET /` 的 JSON 字段；需要接口发现改用 `GET /api`，存活探活改用 `GET /healthz`。
- 确认 `LANDING_ANDROID_DOWNLOAD_URL`、`LANDING_CONTACT_EMAIL`、`LANDING_CONTACT_WECHAT` 在生产配置中已赋值（未配置时按钮显示「即将开放」，不影响发布，但落地页 CTA 不完整）。

## 上线后冒烟

```bash
curl -sI https://<domain>/ | grep -i content-type      # text/html
curl -s  https://<domain>/api | grep -o '"status"'      # JSON 含 status
curl -sI https://<domain>/healthz | grep -E 'HTTP/.*(200|503)'
# 以下行为应与上线前一致：
curl -sI https://<domain>/api/auth | head -1
curl -sI https://<domain>/admin/login | head -1
```

- `GET /` 返回 HTML 落地页；
- `GET /api` 返回 JSON，含 `app`/`status`/`endpoints`；
- `GET /healthz` 返回 200（或数据库异常时 503）；
- `/api/*` 业务接口、`/admin`、`/static/uploads/`、`/media/` 行为不变。

## 回滚

按相反顺序分层回滚，优先恢复公网入口语义：

1. **先回滚 Nginx（PR #18）**：移除 `location = /` 与 `location = /api`，`nginx -t` 通过后 `nginx -s reload`。公网 `/` 立即恢复为原有静态入口。
2. **再回滚后端（PR #17）**：回退后 `GET /` 恢复返回 JSON 接口发现，`GET /api` 路由消失。

禁止在未先回滚 Nginx 的情况下单独回滚后端，否则 `/` 会被反代到旧后端、`/api` 反代到已不存在的路由。
