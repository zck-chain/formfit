# FormFit v1 Flutter Web 同源发布与回滚

本文档面向运维，覆盖 Flutter Web（PWA）产物的**构建、同源 Nginx 托管、1Panel 落地、
发布与回滚**。后端容器、HTTPS 证书、备份等仍见 [`1panel.md`](./1panel.md)；本文只讲
Web 静态产物这一层。

> 适用范围：v1 单机 SQLite 形态，Flutter Web/PWA 与 FastAPI 同源部署在同一域名下，
> 由 Nginx 统一终止 TLS：`/api`、`/media`、`/static` 反代到 `127.0.0.1:8000`，
> 其余路径由 Flutter Web 产物提供。

## 0. 前置条件

- 后端容器已按 [`1panel.md`](./1panel.md) 启动，`curl http://127.0.0.1:8000/healthz`
  返回 `{"status":"ok"}`；
- 服务器已装 Nginx（1Panel「网站 → 反向代理」自带，或独立安装）；
- Flutter SDK ≥ 3.27（仅**构建机**需要，生产服务器不需要 Flutter）；
- 域名已解析到服务器，证书待 W7-1 门禁（本文用占位 `app.example.com`）。

## 1. 同源约定

| 路径 | 归属 | 说明 |
|---|---|---|
| `/api/` | FastAPI | 业务接口（鉴权、评估、计划、支付、会员等） |
| `/admin` | FastAPI | 运营后台（Jinja2 页面 + 表单写操作：登录、发放/收回 PRO、启停用户）；挂在根路径，不在 `/api` 下，必须单独反代 |
| `/media/` | FastAPI 静态 | 数据集只读素材（动作 GIF/JPG/视频） |
| `/static/` | FastAPI 静态 | 后台自带资源 + 用户上传 `/static/uploads`（**写请求必须反代**） |
| `/healthz` | FastAPI | 存活+数据库探活（注意是根路径，非 `/api/healthz`） |
| `/` 及其余 | Flutter Web | `build/web`，深链回退 `/index.html` |

Nginx 配置示例见仓库 `deploy/nginx/formfit-web.conf`（安全头片段在
`deploy/nginx/snippets/security_headers.conf`，部署时放到 nginx prefix 下的
`snippets/`，或把其中 4 行 `add_header` 内联）。**路由顺序是评审重点**：所有反代
前缀必须位于 `/` 静态 + SPA fallback 之前，否则 `/api/...`、`/admin/...` 会被
`try_files` 的 `/index.html` 吞掉，返回 200(HTML) 而非 JSON/后台页面（后台表单 POST
会变成 405）。

缓存策略：

- `assets/`、`canvaskit/`、字体：`Cache-Control: public, max-age=31536000, immutable`
  （Flutter 经 `AssetManifest` 寻址、CanvasKit 随 SDK 版本化，内容变更时清单文件会更新）；
- `index.html`、`main.dart.js`、`flutter.js`、`flutter_bootstrap.js`、
  `flutter_service_worker.js`、`version.json`、`*Manifest*`：`no-cache`（这些文件**不带
  内容哈希**，绝不能 immutable，否则发版后客户端拿不到新包）。

安全响应头（HSTS、`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`）集中在
`deploy/nginx/snippets/security_headers.conf`，在 server 级和每个自带 `add_header` 的静态
location 各 include 一次，避免 nginx 的 `add_header` 继承陷阱导致关键响应丢失安全头。
CSP（内容安全策略）**留待 W6-1 认证硬化**统一处理：应用依赖 `google_fonts`，运行时可能拉
`fonts.googleapis.com`/`fonts.gstatic.com`，需边测边收紧，过严会挡字体（届时切 Cookie 一起做）。

## 2. 构建 Web 产物

在**构建机**（开发机或 CI）上，从要发布的 commit 构建：

```bash
cd formfit_app

# 拉取依赖
flutter pub get

# 同源构建：API_BASE_URL 留空 → 运行期用根相对路径（/api、/media 自动同源）
flutter build web --release \
  --dart-define=API_BASE_URL=

# 产物在 formfit_app/build/web
```

> 同源时 `API_BASE_URL` 必须留空（`=` 后无值）。应用对 `/media/...`、`/static/...`
> 等路径会拼成根相对 URL，由 Nginx 同源反代，不产生跨域。若用绝对地址（如
> `https://app.example.com`）也可，但留空最省事且天然适配域名切换。

按 commit sha 归档（便于回滚）：

```bash
# 在仓库根目录
SHA=$(git rev-parse --short=12 HEAD)
ARTIFACT=/opt/formfit-releases/web-${SHA}.tar.gz

# 在构建机打包 build/web（含 index.html、assets/、canvaskit/ 等）
tar -C formfit_app/build/web -czf "$ARTIFACT" .
sha256sum "$ARTIFACT" > "${ARTIFACT}.sha256"
```

把 `web-${SHA}.tar.gz{,.sha256}` 上传到服务器 `/opt/formfit/releases/`（scp / 1Panel
文件管理 / 对象存储均可）。

## 3. 服务器目录布局

发布采用「版本目录 + `current` 软链」：切版只改软链，回滚秒级。

```text
/opt/formfit/
├── releases/
│   ├── web-<old-sha>/        # 上一版完整产物（回滚用）
│   └── web-<new-sha>/        # 本次发布产物
└── web/
    └── current -> /opt/formfit/releases/web-<new-sha>   # Nginx root 指向这里
```

Nginx 配置 `deploy/nginx/formfit-web.conf` 中：

```nginx
set $web_root /opt/formfit/web/current;
root $web_root;
```

> 用软链切换是为了原子性：`ln -sfn` 改的是目录项，Nginx 已打开的文件描述符不受影响，
> `reload` 后新请求落到新目录。

## 4. 首次部署（1Panel / 独立 Nginx）

### 4.1 放置产物

```bash
# 服务器上
mkdir -p /opt/formfit/releases /opt/formfit/web
cd /opt/formfit/releases

SHA=<本次 sha>
tar -xzf web-${SHA}.tar.gz -C web-${SHA}

# 校验（可选）
sha256sum -c web-${SHA}.tar.gz.sha256

# 切软链
ln -sfn /opt/formfit/releases/web-${SHA} /opt/formfit/web/current
ls -l /opt/formfit/web/current
```

### 4.2 安装 Nginx 配置

把仓库 `deploy/nginx/formfit-web.conf` 拷到 Nginx 的 vhost 目录（独立 Nginx 通常是
`/etc/nginx/conf.d/formfit.conf`；1Panel 网站配置一般在
`/opt/1panel/apps/openresty/openresty/conf/conf.d/<站点>.conf`，以 1Panel 实际路径为准）。

按需替换两处占位：

- `server_name app.example.com;` → 真实域名；
- `ssl_certificate*` 路径 → 1Panel 签发证书的实际路径。

1Panel 落地路径（不实际操作）：

1. 「网站 → 创建网站 → 反向代理」，主域名填 `app.example.com`，代理目标
   `http://127.0.0.1:8000`（这一步会生成基础反代配置）；
2. 进入站点「配置」，把生成的内容替换为 `formfit-web.conf`（保留 1Panel 的证书路径与
   `include` 片段）；
3. 「HTTPS → Let's Encrypt」申请证书并开启**自动续期**、强制 HTTPS、HTTP/2；
4. 确认「网站根目录」可设为 `/opt/formfit/web/current`（若 1Panel 反代站点不允许
   自定义 root，就用「运行环境 → 静态网站」+ 反代 location 的组合，或直接用独立 Nginx）；
5. 保存并「重载」。

> 1Panel 的反代向导默认把 `/` 也代理给后端，这会导致 Flutter Web 产物没被托管。
> 必须用本仓库的配置覆盖，让 `/` 走静态、`/api` 等走反代。

### 4.3 校验并热加载

```bash
nginx -t                 # 语法校验，必须 syntax is ok / test is successful
nginx -s reload          # 或在 1Panel 点「重载」
```

## 5. 发布（升级 Web）

```bash
# 1) 构建机：按第 2 节产出 web-<new-sha>.tar.gz 并上传

# 2) 服务器：解压新版本
cd /opt/formfit/releases
NEW_SHA=<new-sha>
tar -xzf web-${NEW_SHA}.tar.gz -C web-${NEW_SHA}

# 3) 原子切软链 + 热加载（reload 不中断在途请求）
ln -sfn /opt/formfit/releases/web-${NEW_SHA} /opt/formfit/web/current
nginx -t && nginx -s reload

# 4) 冒烟（见第 7 节）
curl -fsS https://app.example.com/healthz
curl -fsS https://app.example.com/             # 200 HTML
curl -fsS https://app.example.com/some/deep/route -o /dev/null -w "%{http_code}\n"  # 200（SPA fallback）
```

后端容器升级（镜像 tag）与 Web 发布相互独立：

```bash
# 仅升后端（数据卷不动，entrypoint 自动跑迁移）
cd /opt/formfit
git fetch --tags && git checkout <new-tag>
docker compose --env-file .env up -d --build
```

### 5.1 容器镜像 tag 约定

`docker-compose.yml` 里镜像固定为 `formfit-backend:latest`。生产建议在发布时打版本 tag：

```bash
docker build -t formfit-backend:<new-sha> -t formfit-backend:latest .
# compose 里把 image 改成 formfit-backend:<new-sha> 后 up -d
```

回滚时把 tag 改回上一版即可（见第 6 节）。

## 6. 回滚

### 6.1 仅回滚 Web 产物（最常见：前端发版有问题）

```bash
cd /opt/formfit/web
ls -l current                          # 看当前指向哪个 sha
ln -sfn /opt/formfit/releases/web-<old-sha> current
nginx -t && nginx -s reload
```

秒级生效，无需重启容器。保留最近至少 2 个版本目录再清理。

### 6.2 回滚后端镜像

```bash
cd /opt/formfit
# 把 docker-compose.yml 的 image tag 改回上一版
sed -i.bak 's|formfit-backend:.*|formfit-backend:<old-sha>|' docker-compose.yml
docker compose --env-file .env up -d
```

数据卷不动，挂载的是同一份 SQLite/上传。若新版本迁移需要回退 schema，先在停机窗口
`alembic downgrade <revision>` 再回滚镜像（详见 `1panel.md` 第 8 节）。日常升级应保持
向后兼容迁移以简化回滚。

### 6.3 Nginx 配置回滚

```bash
# 改回上一份 conf 后
nginx -t && nginx -s reload
# 极端情况 reload 异常可直接 restart（会秒级断连）
systemctl restart nginx
```

## 7. 本地验证（容器化，可复现）

无需真实域名/证书即可在本机验证路由。在仓库根目录提供了一个**临时** Nginx 验证服务，
挂到 `docker-compose` 旁一起起：

```bash
# 0) 先有 build/web 产物（见第 2 节，或用任意 Flutter 工程构建）
cd formfit_app && flutter build web --release --dart-define=API_BASE_URL= && cd ..

# 1) 起后端 mock + 临时 nginx（独立、临时，见 deploy/nginx/docker-compose.verify.yml）
docker compose -f deploy/nginx/docker-compose.verify.yml up -d

# 2) 验证（HTTP 明文，仅本地）
NG=http://127.0.0.1:8080

# 首页 / SPA fallback
curl -sS -o /dev/null -w "GET /            -> %{http_code}\n" $NG/
curl -sS -o /dev/null -w "GET /assessment  -> %{http_code} (SPA fallback)\n" $NG/assessment/123

# 反代：健康检查（根路径 /healthz）
curl -sS -w "\nhealthz -> %{http_code}\n" $NG/healthz

# 反代：/api 不被 SPA 吞（应返回 JSON，而非 index.html）
curl -sS $NG/api/exercises/ 2>/dev/null | head -c 200; echo

# 反代：/admin 运营后台（页面 + 表单写操作都必须反代，不能被 SPA fallback 吞）
curl -sS -D - "$NG/admin/login" -o /tmp/admin.html \
  | grep -iE "HTTP/|content-type|x-mock"
grep -c "<!-- admin -->" /tmp/admin.html   # 期望 1（后端后台标记，非 Flutter index.html）
# 收回 PRO 的表单 POST 必须透传到后端，而不是被静态区返回 405
curl -sS -X POST "$NG/admin/membership/1/revoke" -F "reason=test" ; echo

# 反代：/media 数据集素材
curl -sS -o /dev/null -w "GET /media        -> %{http_code}\n" $NG/media/exercises/images/

# 上传体积上限：>12MB 应被 Nginx 直接 413（不到后端）
dd if=/dev/zero of=/tmp/big.jpg bs=1m count=13 2>/dev/null
curl -sS -o /dev/null -w "upload 13MB       -> %{http_code} (期望 413)\n" \
  -F "file=@/tmp/big.jpg" $NG/api/fitness/assess

# index.html 应同时带 no-cache 与安全头（验证 add_header 继承修复）
curl -sS -D - -o /dev/null "$NG/index.html" | grep -iE "cache-control|x-frame-options|x-content-type"

# 配置语法
docker compose -f deploy/nginx/docker-compose.verify.yml exec nginx nginx -t

# 3) 验证完拆除临时服务
docker compose -f deploy/nginx/docker-compose.verify.yml down
```

验收点：

| 检查 | 期望 |
|---|---|
| 刷新深链 `/assessment/123` | 200（HTML，SPA fallback） |
| `/healthz` | 200 `{"status":"ok"}` |
| `/api/exercises/` | JSON（被反代到后端，非 HTML） |
| `GET /admin/login` | 200 `text/html`，带后端标记 `<!-- admin -->` / `X-Mock: admin`（**非** Flutter index.html） |
| `POST /admin/membership/{id}/revoke` | 200（表单 POST 透传后端，非静态区 405） |
| `/media/exercises/images/...` | 200（素材可达） |
| 上传 13MB | 413（Nginx 层拦截，与后端 10MB 上限对齐） |
| `/index.html` 响应头 | 同时有 `Cache-Control: no-cache` 与 `X-Frame-Options`/`X-Content-Type-Options`（安全头未被 add_header 继承丢弃） |
| HTTP→HTTPS | 301（生产；本地 verify 为明文 HTTP，不验证跳转） |

> HTTP→HTTPS 跳转与 HSTS 依赖证书，本地 verify compose 只验路由与反代；跳转逻辑可在
> `nginx -t` 配置评审中确认（80 server 块 `return 301 https://...`）。

### compose 片段（`deploy/nginx/docker-compose.verify.yml`）

该文件**仅用于本地验证**，不要用于生产：它用 stdlib mock 后端
（`deploy/nginx/verify/mock_backend.py`，模拟 `/healthz`、`/api`、`/admin`（页面 + 表单
POST）、`/media`、`/static` 与上传回显）替换真实 FastAPI，无需密钥/数据库/构建后端镜像。
生产用 1Panel/独立 Nginx 加载 `deploy/nginx/formfit-web.conf`。

## 8. 发布前人工门禁（W7-1）

以下不在本文范围，需产品/运维提供后才能真正上线：

- 真实域名与 ICP 备案；
- Let's Encrypt/商业证书申请与自动续期；
- 与后端 `CORS_ORIGINS` 对齐（同源可留空，仅同源放行）；
- 上传目录（`/data/uploads`）与数据库的备份策略（见 `1panel.md` 第 5 节）。
