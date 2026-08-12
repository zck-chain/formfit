# W7-1 发布门禁 QA 测试报告

- 任务：WS-44「跨浏览器/真机闭环与发布验收」
- 测试基线：`main` HEAD `c30f0f5`（Stage 5/6 全部合入）
- 测试分支：`w7-qa-release-gate`
- 测试日期：2026-08-12
- 测试人：QA 测试工程师

## 0. 结论摘要

**代码层门禁（A 部分，本机可执行）全部跑通，发现 2 个 major、3 个 minor，不建议直接公开发布。**

后端 144 个 pytest、前端 49 个 test + analyze、Web 同源构建、Nginx 同源路由（Docker 实证）、备份恢复演练、生产 fail-fast 均通过。但发布门禁清单第 3、4 条未完全满足：

- 管理员审计**只写不查**，后台没有审计查看页面（门禁要求「审计可查」）。
- 前端付费墙在 Web 上**仍渲染「立即开通 PRO」下单按钮**并发起 `POST /api/payment/orders`，仅靠后端 403 兜底，未满足「前端无下单 CTA」。

后端 Kill Switch 本身牢靠（关闭时任意渠道下单 403、无副作用），因此**不存在真实资金风险**；上述两项属于门禁验收口径与体验/可观测性缺口。

**真机/生产/AI Key 相关验收（B 部分）被外部资源阻塞，未执行**，见 §4。需要产品负责人提供：真机、服务器 SSH/1Panel、域名+证书、DeepSeek/DashScope 真实 Key。

---

## 1. 测试范围与环境

| 维度 | 内容 |
|---|---|
| 后端 | Python 3.14（.venv），pytest 9.1.1，SQLite |
| 前端 | Flutter（`~/flutter`），`formfit_app/` |
| Web 服务器 | nginx:1.27-alpine（Docker verify 编排）+ mock 后端 |
| 备份恢复 | 直接运行 `app/ops/backup.py` / `restore.py` 对真实 `formfit.db` 做演练（恢复到临时目录，未触碰原库） |

测试覆盖发布门禁清单（WS-37 §4）第 3、4、5、6、7、9 条的**代码/本地可验证部分**；第 1、2、8 条与真机、生产部署、AI 真实输出相关，列为 B 部分阻塞。

---

## 2. 代码层门禁结果（A 部分）

### 2.1 后端单元/集成测试 —— ✅ 通过
- 命令：`python -m pytest -q`
- 结果：**144 passed**（30.4s），9 条 deprecation warning（starlette/slowapi，非缺陷）。
- 覆盖：支付 Kill Switch、管理员审计、Cookie/CSRF、会员门控、支付并发/幂等、备份恢复、部署硬化、限流、HEIC 转码、上传校验、E2E 旅程。

### 2.2 支付下单 Kill Switch —— ✅ 后端通过 / ⚠️ 前端见缺陷 F-2
- `app/api/routes/payment.py:69` 在 `create_order` 最前面拦截：`CHECKOUT_ENABLED=false` 时直接 `403 {"error":"checkout_disabled"}`，不进 provider、不建 Order、不生成凭证。
- 只读接口 `GET /api/payment/plans`、`/channels` 仍可用。
- 测试 `test_admin_audit_checkout.py` 覆盖：关→403 且无订单、关→所有渠道拦截、开→sandbox 流程不变、关时套餐只读可用。
- `CHECKOUT_ENABLED` 默认 `False`（`app/core/config.py:130`、`.env.example:101`）。

### 2.3 Web Cookie + CSRF 认证 —— ✅ 通过
- `app/core/web_auth.py`：`ff_session` 为 `HttpOnly`，`csrftoken` 可读（双提交）；`Secure` 跟随环境（生产强制 true）；`SameSite=Lax`；常量时间比对 `secrets.compare_digest`。
- `app/api/deps.py`：Bearer 优先、cookie 兜底；cookie 写操作（POST/PUT/PATCH/DELETE）缺/错/不匹配 CSRF 一律 `403 csrf_failed`，且 CSRF 在认证前校验；GET 等安全方法免校验；带 Bearer 头的 native 链路免 CSRF。
- 端点 `/api/auth/web-login`、`/api/auth/csrf`、`/api/auth/web-logout` 齐全；登出清除 cookie。
- 测试 `test_web_cookie_csrf.py` 16 例全过：登录下发双 cookie、失败不下发、Secure 跟随环境、cookie GET 免 CSRF、正确/缺失/错误/不匹配 CSRF、Bearer 优先于无效 cookie、Bearer 登录仍可用、登出吊销、完整会话流。
- 边界说明：管理员后台 `/admin/*` 使用独立的 itsdangerous cookie（`formfit_admin`，HttpOnly+SameSite=Lax+生产 Secure），其写操作**无独立 CSRF token**，仅靠 SameSite=Lax 缓解——见缺陷 F-3。

### 2.4 管理员发放/收回/启停审计 —— ⚠️ 写入完整，查看缺失（F-1）
- `app/api/routes/admin.py`：`grant_membership`、`revoke_membership`、`toggle_user` 均在同事务内写 `admin_audit_events`（before/after 快照、reason、idempotency_key、request_id）。
- 约束已实现并测试：发放/收回 reason 必填；禁止操作其他 admin（403）；支持永不过期（days=0 → expire_at=None）；`Idempotency-Key` 去重并留痕；迁移 upgrade/downgrade 可逆。
- 测试 11 例全过（`test_admin_audit_checkout.py`）。
- **缺口**：审计事件只写库，后台无任何查询路由/页面（见 F-1）。

### 2.5 备份恢复演练 —— ✅ 通过
对真实 `formfit.db`（27MB）执行完整演练（恢复目标全部在临时目录）：
1. `python -m app.ops.backup --db formfit.db --out <tmp>` 生成一致性快照 + `.sha256`，备份内 `PRAGMA integrity_check` 通过。
2. `python -m app.ops.restore --snapshot <snap> --target <tmp>/restored.db` 恢复成功；恢复后库可打开、`integrity_check=ok`、核心表行数正确（users=8, memberships=8, body_assessments=1, plans=3, workout_logs=1, orders=0）。
3. 负向-防误覆盖：目标已存在且未加 `--force` → 拒绝并退出码 2。
4. 负向-防篡改：篡改快照一字节但保留校验文件 → SHA-256 校验失败、拒绝恢复（退出码 1）。

### 2.6 生产 fail-fast —— ✅ 通过（子进程实测）
`APP_ENV=production` 下逐项实测拒绝启动：
- 默认/弱密钥（`JWT_SECRET=changeme`、`ADMIN_SESSION_SECRET` 为默认值）→ `RuntimeError: 生产环境安全校验失败，拒绝启动`。
- `PAYMENT_CHANNELS=sandbox` → 拒绝（生产不得启用沙箱渠道）。
- `WEB_CONCURRENCY=2`（SQLite 多 worker）→ 拒绝。
- 另：内存库 `:memory:` 也会被拒（测试覆盖）；强密钥+合规配置可正常启动。`CHECKOUT_ENABLED=true` 在生产仅告警不阻断（为商业化预留，符合设计）。

### 2.7 前端 analyze / test / build —— ✅ 通过
- `flutter analyze`：**No issues found**。
- `flutter test`：**49 tests passed**（含 Web 上传平台拆分、配置同源拼接、支付控制器、付费墙 widget、响应式断点、轮询状态机）。
- `flutter build web --dart-define=API_BASE_URL=`：**Built build/web** 成功；产物中无 `.env` 泄漏。

### 2.8 Nginx 同源配置（Docker 实证）—— ✅ 通过
用仓库自带 `deploy/nginx/docker-compose.verify.yml`（nginx:1.27-alpine + mock 后端 + 真实 `build/web`）启动，断言 9/9 通过：

| 检查 | 结果 |
|---|---|
| `/` 返回 index.html（200 text/html） | ✅ |
| 深链 `/assessment/123` SPA fallback 到 index.html（非 404） | ✅ |
| `/api/*` 被反代（返回 JSON 回显，非 HTML） | ✅ |
| `/admin/login` 被反代（返回 mock admin 标记，非 Flutter index.html） | ✅ |
| `POST /admin/membership/1/revoke` 反代成功（非静态区 405） | ✅ |
| `/media/*` 返回图片 | ✅ |
| `/static/*` 被反代 | ✅ |
| `/healthz` 返回 ok | ✅ |
| `index.html` 为 `no-cache`、带哈希资源为 `immutable` 且带安全头 | ✅ |

附加核对：不存在的哈希资源返回 404（`try_files =404`）；生产 conf 含 HTTP→HTTPS 跳转、HSTS、`location ~ /\.` 拒绝点文件（静态审查确认 `deploy/nginx/formfit-web.conf:230`，因 verify 配置为 HTTP 明文未含 TLS/点文件规则，该项**未经运行时验证**，列入 B 部分在生产 nginx 上复验）。

---

## 3. 缺陷清单

### F-1 [MAJOR] 管理员审计「只写不查」，后台无审计查看入口
- 复现：登录 `/admin`，侧边栏只有 看板/用户/会员/动作（`app/templates/admin/base.html:60-72`）；`app/api/routes/admin.py` 中对 `admin_audit_events` 只有 `record_event` 写入，无任何 list/查询路由；`app/templates/admin/` 无 audit 模板。
- 预期（门禁 §4.3）：管理员发放/收回/启停「审计可查」，能按时间/操作者/目标用户回溯操作记录。
- 实际：审计行写入数据库，但只能直连 SQLite 查询，运营者在后台看不到。
- 影响：误操作追责、撤销依据在 UI 层不可达；门禁「可查」未满足。撤销能力本身（revoke=置 is_active=false/expire_at=now 并留痕）已具备，但没有基于审计日志的操作历史视图。
- 建议：新增 `GET /admin/audit`（分页、按 action/admin/target 过滤）+ `audit.html`，复用既有 `require_admin`；敏感字段已在模型层白名单化，直接序列化 before/after/reason/request_id/created_at 即可。
- 归属：Stage 5 W5-2 范围（管理员审计），建议打回后端补「查」的部分。

### F-2 [MAJOR] Web 付费墙仍渲染「立即开通 PRO」并发起真实下单，未满足「前端无下单 CTA」
- 复现：Web 构建后，从首页额度面板（`quota_panel.dart:36`）、个人页（`profile_tab.dart:112`）或 PRO gate（`pro_gate.dart:135`）进入付费墙；`PaywallScreen` 始终渲染 `GlowButton(label: 立即开通 PRO, onTap: controller.purchase)`（`paywall_screen.dart:139-144`）；点击后 `PaymentController.purchase()` 对 sandbox 渠道调用 `_repo.createPaymentOrder(...)`（`payment_controller.dart:198`）→ `POST /api/payment/orders` → 后端返回 403 `checkout_disabled`，前端进入 error 态显示该错误。
- 预期（ADR-2 / 门禁 §4.4）：v1 免费自用版前端**不渲染真实下单 CTA**（或展示「暂未开放，联系管理员开通」）；后端 403 是兜底，不应成为用户正常路径。
- 实际：按钮可点，点了必然报错；体验上像「坏了的支付」，且与定稿口径不符。
- 安全影响：**无真实资金风险**——后端 Kill Switch 牢靠，关闭时不建单、不调 provider。属于门禁验收/体验缺口，而非可被利用的下单漏洞。
- 建议：Web 构建下（`kIsWeb` 或读后端 checkout 开关）付费墙隐藏/禁用下单与恢复按钮，替换为「PRO 暂未开放自助开通，请联系管理员」；保留只读套餐展示可选。native（iOS/macOS）走 Apple 内购的路径维持不变。
- 归属：前端（W5-1/W6 付费墙适配），建议打回前端。

### F-3 [MINOR] 管理员后台写操作无独立 CSRF token，仅靠 SameSite=Lax
- 位置：`app/api/routes/admin.py:163+`（toggle/grant/revoke）。
- 说明：`formfit_admin` cookie 设了 `HttpOnly; SameSite=Lax; Secure(生产)`，现代浏览器中 Lax 会阻止跨站 POST 附带 cookie，因此**当前不可直接被 CSRF 利用**；但与 App Web 路径（`ff_session` + 双提交 CSRF token）口径不一致，属纵深防御缺口。旧版浏览器或未来引入 SameSite=None 跨站嵌入场景下风险会上升。
- 建议：为后台表单加 CSRF token（与 App web 复用双提交方案，或 Jinja2 表单内隐字段 + 服务端校验）。
- 优先级：自用单管理员产品可在公开发布前补，不阻塞代码层。

### F-4 [MINOR] Nginx 生产配置中 AssetManifest 的 no-cache 规则被 `/assets/` 优先匹配而失效
- 位置：`deploy/nginx/formfit-web.conf:188`（`location ^~ /assets/` 设 immutable）与 `:216`（正则想给 AssetManifest 设 no-cache）。
- 说明：`^~ /assets/` 是带 `^~` 的前缀匹配，会优先于正则 location，导致 `AssetManifest.json`（位于 `/assets/` 下、文件名无内容哈希）实际拿到 `max-age=31536000, immutable`。`:216` 那条针对 AssetManifest 的正则是**死代码**，与其注释意图相反。
- 影响：发版后部分浏览器可能在一年内缓存旧的 AssetManifest，导致新资源寻址滞后（Flutter 框架加载清单通常带缓存破坏，实际影响小，但配置自相矛盾）。
- 建议：要么把 AssetManifest 移出 immutable 范围（单独 `location = /assets/AssetManifest.json` 设 no-cache，注意 `=` 精确匹配优先级最高），要么删除 `:216` 中针对 AssetManifest 的无效片段并注释说明。

### F-5 [MINOR] 生产环境默认公开 FastAPI 文档端点
- 位置：`app/main.py:33`（`FastAPI(...)` 未按环境关闭 `docs_url`/`redoc_url`/`openapi_url`），`deploy/nginx/formfit-web.conf:174-176` 反代 `/docs`、`/redoc`、`/openapi.json`。
- 影响：公网可浏览完整接口结构，属轻微信息暴露（接口本身有鉴权，不构成直接漏洞）。
- 建议：生产设 `docs_url=None`（或加管理员/IP 白名单），并按需删除 nginx 的 docs 反代块。自用产品可接受，记录在案。

### F-6 [INFO] 响应头缺 CSP
- 位置：`deploy/nginx/snippets/formfit-security-headers.conf` 只有 HSTS/XCTO/XFO/Referrer-Policy，CSP 仍是注释草稿。
- 说明：定稿将 CSP 留到认证硬化阶段；当前 Cookie 已是 HttpOnly，XSS 窃取会话面显著降低，但 CSP 仍是推荐的纵深防御。
- 建议：公开发布前按注释草稿收紧 `connect-src 'self'`、`img-src 'self' data: blob:`，并实测 google_fonts 不受影响。

---

## 4. 未执行项（B 部分，阻塞于外部资源）

以下发布门禁项**无法在本机/无资源条件下验证**，需产品负责人提供资源后补测：

| 门禁项 | 阻塞资源 | 备注 |
|---|---|---|
| §4.1 手机 Safari/Chrome + 桌面 Safari/Edge 端到端闭环 | 真机、桌面 Safari/Edge | 本机仅能跑 headless Chrome；无 E2E runner 做浏览器矩阵 |
| §4.2 真机拍照/相册选图（权限拒绝/重选、HEIC 兜底） | iPhone Safari、Android Chrome 各≥1 真机 | HEIC 转码后端有单测（`test_upload_heic_transcoded_to_jpeg`），真机拍摄/选图链路未验 |
| §4.6 生产 HTTPS/同源深链/缓存/回滚演练、点文件拒绝、HSTS | 服务器 43.139.153.162 的 SSH/1Panel、已备案域名+证书 | 本地用 HTTP 的 verify 编排验证了路由；TLS、证书、真实回滚切软链需在生产复验 |
| §4.8 AI 真实输出质量（动作来自库、无编造、禁忌排除、安全提示） | DeepSeek、DashScope/Qwen-VL 真实 Key + 预算 | 代码层有 mock/保底，真实输出需按定稿「评估≥10 张、计划≥5 份」由产品本人签字 |
| 生产 `.env` 真实启动 | 服务器 | 强密钥/CHECKOUT_ENABLED/PAYMENT_CHANNELS 在真实环境的启动校验 |

已有可用的部署文档：`docs/deployment/web-release.md`、`docs/deployment/1panel.md`，以及架构师此前为 43.139.153.162 出具的《部署指南》。

---

## 5. 建议与发布结论

1. **打回修复 F-1、F-2 后再进入公开发布门禁**；两项均为小范围改动（一个后台只读页、一个 Web 付费墙 CTA 门控），不涉及核心业务逻辑。
2. F-3/F-4/F-5/F-6 可在发布前一并处理或记录为已知项，不阻断代码冻结。
3. B 部分在产品提供真机/服务器/域名/AI Key 后，由 QA 按本报告 §4 表格逐项补测并出补充报告；其中 AI 真实输出的合格判定建议按 WS-37 §6 问题4 由产品本人签字。
4. 备份恢复、Kill Switch、生产 fail-fast、Cookie/CSRF 四项核心安全/可靠性门已有自动化测试与本次实测背书，回归可重复。
