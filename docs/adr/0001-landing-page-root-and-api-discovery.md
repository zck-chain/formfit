# ADR 0001：公网根路径归落地页，接口发现迁移到 /api

- 状态：accepted
- 日期：2026-08-17
- 关联：WS-50（落地页）、WS-52（入口边界审查）、WS-55（本 ADR）、PR #17（后端落地页）、PR #18（Nginx 精确反代）

## 背景

产品方向已由产品负责人确认：

- 用户主入口继续是 **Flutter Android App**，不恢复 Flutter Web/PWA 用户端方案，也不引入 React/Next/shadcn。
- 公网 Web 端只承担两类职责：
  1. `GET /` 由 FastAPI/Jinja2 渲染的**介绍落地页**（产品亮点、动作库展示、Android 下载入口、联系方式）；
  2. `/admin` 运营后台（Jinja2 页面 + 表单写操作）。

在该方向之前，公网根路径 `GET /` 返回 JSON 接口发现信息（应用名、状态、各业务接口前缀）。WS-50 的 PR #17 已将 `GET /` 改为 HTML 落地页，并把原 JSON 接口发现迁移到 `GET /api`；PR #18 同步调整 Nginx 入口边界。WS-52 审查确认方向可行，但要求在合并前补齐本 ADR，以固化根路径语义变更与入口边界。

## 决策

### 1. 根路径语义

- `GET /` 返回 **HTML 落地页**（FastAPI/Jinja2 模板 `app/templates/landing.html`，路由 `app/main.py:landing`）。
- 原根路径 JSON 接口发现迁移到 `GET /api`（路由 `app/main.py:api_index`），返回应用名、运行状态、`/docs` 及各业务接口前缀。
- `/healthz` 继续作为存活 + 数据库探活端点（公网可仅返回 200/503，不含敏感信息）；`/health` 保留为旧探针兼容。

### 2. Nginx 入口边界

在 `deploy/nginx/formfit-web.conf` 中：

- `location = /`：精确匹配，反代到 FastAPI 后端渲染落地页。精确匹配 `=` 优先级最高，必然先于静态区 `location /` 命中，不依赖书写顺序。
- `location = /api`：精确匹配，反代到后端的 JSON 接口发现。必须显式补这条，因为既有 `location ^~ /api/` 只命中带尾斜杠前缀，无尾斜杠的 `/api` 否则会掉进 SPA fallback 返回 Flutter `index.html`（200 HTML，不是 JSON）。
- 以下前缀继续反代到后端：
  - `location ^~ /api/`（业务接口）
  - `location ^~ /admin`（运营后台，含表单 POST）
  - `location = /healthz`（探活）
  - `location ^~ /static/`（后台静态资源 + `/static/uploads` 用户上传，上传写请求必须反代）
  - `location ^~ /media/`（数据集只读素材）

Flutter Web 产物目录的静态资源规则（`/assets/`、`/canvaskit/`、字体、`index.html`、启动脚本等）与 SPA fallback `location /` 保持不变；它们仅在落地页与后台之外的路径生效。由于所有反代前缀均以 `=` 或 `^~` 优先匹配，不会被 SPA fallback 吞掉。

## 备选方案

- **保持 `/` 返回 JSON，落地页放 `/home` 或 `/landing`**：不采用。产品与传播层面要求裸域名即落地页；把 JSON 挤到非根路径反而让“访问官网看到接口 JSON”的现状延续。
- **由 Nginx 直接服务静态落地页 HTML，不经 FastAPI**：不采用。落地页需要运行时注入 Android 下载链接与联系方式（见 `landing_*` 配置），且与后台共用 Jinja2 模板同源；经 FastAPI 渲染改动最小、配置可热更新。
- **用 Nginx `return`/`rewrite` 把 `/` 跳到静态页**：不采用。多一次跳转，且同样无法做服务端配置注入。

## 影响与兼容

- **破坏性变更（公网根路径语义）**：任何依赖 `GET /` 返回 JSON 的旧脚本、联调探针、外部探活，必须改用 `GET /api`（接口发现）或 `GET /healthz`（存活/DB 探活）。合并前需确认监控、巡检、上线脚本没有抓取 `/` 的 JSON 字段。
- 落地页为公开页面，不要求登录；下载链接与联系方式由 `LANDING_ANDROID_DOWNLOAD_URL`、`LANDING_CONTACT_EMAIL`、`LANDING_CONTACT_WECHAT` 等配置注入，未配置时按钮显示「即将开放」，不泄露内部信息。
- Nginx 仅调整入口路由，不改变上游（单 worker FastAPI 绑 `127.0.0.1:8000`）、TLS、安全头、缓存与上传体积策略。
- 本变更不影响 `/api/*` 业务接口、`/admin` 后台、上传与素材服务的现有契约。

## 合并与部署顺序

必须严格按顺序，避免 `/` 在线上短暂返回旧 JSON 或半成品入口：

1. **先合并并部署 PR #17**（后端落地页 `feat/landing-page`）：后端同时具备 `GET /`（HTML）与 `GET /api`（JSON）。此时 Nginx 尚未把 `/` 反代到后端，公网 `/` 仍由 Flutter Web 产物提供，`/api` 仍落入 SPA fallback —— 但因后端已就绪，随后切 Nginx 不会出现后端还不能渲染落地页的空窗。
2. **再合并并发布 PR #18**（Nginx 精确反代 `chore/nginx-landing-proxy`）：上线 `location = /` 与 `location = /api`，执行 `nginx -t` 后 `nginx -s reload`。此时公网 `/` 变为后端落地页，`/api` 返回 JSON 接口发现。

详细回滚与验证步骤见 `docs/deployment/landing-api-discovery-rollout.md`。

## 回滚方式

按与上线相反的顺序分层回滚，优先恢复公网入口语义：

1. 先回滚 Nginx（PR #18）：移除 `location = /` 与 `location = /api` 两条精确反代，`nginx -t` 通过后 `nginx -s reload`。公网 `/` 立即恢复为原有静态入口，`/api` 回到 SPA fallback。
2. 再回滚后端落地页（PR #17）：回退后 `GET /` 恢复返回 JSON 接口发现，`GET /api` 路由消失。由于步骤 1 已先撤掉 `/` 与 `/api` 的精确反代，不会出现 Nginx 把流量导向一个已不存在的 `/api` 后端路由的情况。

禁止在未先回滚 Nginx 的情况下单独回滚后端，否则 `/` 会被反代到旧后端、`/api` 反代到一个不存在的路由，造成公网报错。

## 验证

- 后端：`pytest tests/test_landing_page.py`（落地页 200、`/api` JSON 字段、未配置时按钮文案）。
- Nginx：`nginx -t`；本地可用 `deploy/nginx/docker-compose.verify.yml` 与 `deploy/nginx/verify/` 下的校验配置验证路由优先级与缓存规则。
- 上线后冒烟：
  - `GET /` 返回 `Content-Type: text/html` 且包含落地页标题/下载区；
  - `GET /api` 返回 JSON，含 `app`/`status`/`endpoints`；
  - `GET /healthz` 返回 200/503；
  - `GET /api/auth` 等业务接口、`/admin`、`/static/uploads/`、`/media/` 行为不变。
