# FormFit — AI 健身私教

双端产品：Flutter App（iOS/Android 用户端）+ FastAPI 后端与 Web 管理后台。基于 `exercises-dataset` 的 1324 个动作，提供体态拍照评估、个性化训练计划生成、动作百科、训练记录与会员支付能力。

> 状态：后端业务闭环、Flutter App 与支付（支付宝/微信/沙箱渠道）已完成，自动化 QA 覆盖核心闭环。生产部署见 `docs/deployment/1panel.md`（v1：单台 1Panel 服务器 + SQLite 单 worker + 每日备份）。

## 技术栈

- **后端**：Python 3.11+ · FastAPI · SQLAlchemy 2 · SQLite（ORM 可平滑迁移 PostgreSQL）
- **AI**：DeepSeek（对话/计划编排）+ 通义千问 Qwen-VL（看图评估）
- **前端**：Flutter App（`formfit_app/`）；后台 Jinja2 + 原生 CSS/JS
- **鉴权**：App 用 JWT，后台用签名 cookie session

## 快速开始

```bash
cd FormFit

# 1. 创建虚拟环境并安装依赖
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入 DEEPSEEK_API_KEY 和 DASHSCOPE_API_KEY
# 没填 key 也能启动，AI 会返回占位/保底结果，方便先看界面

# 3. 导入 1324 个动作到数据库（生成 formfit.db）
.venv/bin/python -m scripts.seed_exercises

# 4. 启动服务
.venv/bin/uvicorn app.main:app --reload
```

打开：

- API 文档（Swagger）：http://127.0.0.1:8000/docs
- Web 管理后台：http://127.0.0.1:8000/admin
  - 默认账号见 `.env` 的 `ADMIN_EMAIL` / `ADMIN_PASSWORD`（请务必修改）

## 核心 API

| 方法 | 路径 | 说明 | 鉴权 |
|---|---|---|---|
| POST | `/api/auth/register` | 注册，返回 JWT | 公开 |
| POST | `/api/auth/login` | 登录 | 公开 |
| GET | `/api/exercises` | 动作检索（部位/器械/目标肌/关键词/禁忌过滤） | 公开 |
| GET | `/api/exercises/facets` | 可选筛选维度（中英文） | 公开 |
| PUT | `/api/fitness/profile` | 填写/更新身体数据与训练偏好 | JWT |
| POST | `/api/fitness/assess` | 上传照片，Qwen-VL 评估增肌/减脂/康复方向 | JWT |
| POST | `/api/fitness/plans/generate` | 生成个性化训练计划（带 GIF + 中文步骤） | JWT |
| GET | `/api/fitness/plans` | 我的计划列表 | JWT |
| POST | `/api/fitness/logs` | 记录一次训练（重量/组数） | JWT |
| GET | `/api/membership` | 会员状态与剩余额度 | JWT |
| POST | `/api/payment/orders` | 创建支付订单（沙箱/支付宝/微信） | JWT |
| POST | `/api/payment/callback/{channel}` | 支付渠道异步回调（验签） | 公开 |
| GET | `/healthz` | 存活 + 数据库探活（编排探针） | 公开 |

## 生产部署

v1 为单台腾讯云 1Panel 服务器、Docker 单容器、`uvicorn --workers 1`、SQLite + 每日备份。完整步骤见 [`docs/deployment/1panel.md`](docs/deployment/1panel.md)，要点：

- `/healthz` 含数据库轻量探活，异常返回 503 且不泄露任何敏感信息；
- 生产默认密钥/弱密码、沙箱支付、多 worker、内存库会 fail-fast 拒绝启动；
- SQLite 备份用在线 `.backup` API 生成一致性快照 + SHA-256 + 14 天保留；恢复脚本默认拒绝覆盖；
- 日志为 JSON 输出到 stdout，由 Docker/1Panel 采集轮转，不记录 JWT/密钥/完整回调/用户照片。

## 智能体如何工作

计划生成不是把 1324 个动作塞进提示词，而是：

1. 把用户档案 + 视觉评估方向组装成 system prompt；
2. 向 DeepSeek 提供 `search_exercises` 工具（function calling）；
3. 模型自行按训练日/部位多次检索真实动作；
4. 模型输出结构化计划 JSON；
5. 服务端用数据库**二次校验每个 exercise_id**，补上 GIF 与中文步骤，
   任何编造的 ID 都会被剔除——保证计划里的动作真实存在且可展示。

## Web 管理后台

设计遵循"力量训练控制台"语言：粉笔白底、铁灰文字、杠铃片红作为唯一强调色，KPI 卡片底部有"装载杆"作为 signature。

- **数据看板**：注册/会员/计划/评估/训练记录 KPI、14 天新增趋势、评估方向分布、最近用户
- **用户管理**：搜索、启用/停用
- **订阅与支付**：会员状态查看、手动开通 PRO；沙箱/支付宝/微信订单
- **动作库**：按部位/器械/名称筛选，GIF 网格浏览

## 项目结构

```
app/
├── main.py                 # FastAPI 入口、中间件、路由、静态资源、/healthz
├── startup.py              # 建表、创建默认管理员
├── core/                   # 配置、安全(JWT/密码)、后台 session、限流、结构化日志、健康检查
├── db/session.py           # SQLAlchemy 引擎与会话
├── models/                 # ORM 模型：Exercise/User/Plan/Order...
├── schemas/                # Pydantic 请求/响应模型
├── services/               # 动作检索、后台统计、会员配额
├── agent/                  # DeepSeek / Qwen-VL 客户端、计划生成器
├── payment/                # 支付渠道：sandbox / alipay / wechat（含回调验签、RSA/AES-GCM）
├── ops/                    # SQLite 一致性备份/恢复
├── api/
│   ├── deps.py             # 鉴权依赖
│   └── routes/             # auth / exercises / fitness / admin / membership / payment
├── templates/admin/        # 后台 Jinja2 页面
└── static/                 # 后台 CSS/JS（用户上传落到持久卷 UPLOAD_DIR）
scripts/
├── seed_exercises.py       # 动作数据导入
├── backup_sqlite.sh        # 1Panel 计划任务：每日一致性备份
├── restore_sqlite.sh       # 手动恢复（默认拒绝覆盖）
└── docker-entrypoint.sh    # 容器入口：迁移/种子/启动
docs/deployment/1panel.md   # 生产部署、HTTPS、备份恢复、升级回滚
exercises-dataset/          # 原始 1324 动作数据集（原样保留）
formfit_app/                # Flutter App（iOS/Android）
```

## 路线图

- ✅ 后端地基 + AI 核心（P0/P1）
- ✅ Flutter App：登录、拍照评估、计划展示、跟练记录、付费墙（P2）
- ✅ 会员权限 + 共享月度配额 + 沙箱/支付宝/微信支付（P4，真实商户凭证待接入）
- 后台动作库 CRUD、更丰富的数据看板（P3）
- 摄像头实时动作纠错（MediaPipe 姿态点 + 规则/模型，P5）
- v1 首发 Android；iOS / App Store IAP 在发布 iOS 版本时再做
- 容量增长后：SQLite → PostgreSQL，应用层限流 → Redis 共享存储

## 安全与合规说明

- 所有 AI 评估均为初步参考，**不构成医学诊断**；"康复"仅做安全提示与就医建议。
- 默认 `JWT_SECRET`、`ADMIN_PASSWORD` 仅用于本地开发；生产环境使用占位/弱值会 fail-fast。
- 用户上传的照片/视频存于 `UPLOAD_DIR`（本地默认 `app/static/uploads/`，生产为持久卷 `/data/uploads`），不入库、文件名随机化。
- 生产部署、备份恢复与升级回滚见 `docs/deployment/1panel.md`。
