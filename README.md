# FormFit — AI 健身私教后端

基于 `exercises-dataset` 的 1324 个动作，提供体态拍照评估、个性化训练计划生成、动作百科与训练记录能力。包含一个面向运营的 Web 管理后台。

> 状态：**P0 + P1 已完成**（后端 + AI 核心 + 管理后台）。Flutter App、支付接入、摄像头动作纠错为后续阶段。

## 技术栈

- **后端**：Python 3.11+ · FastAPI · SQLAlchemy 2 · SQLite（可平滑迁移 PostgreSQL）
- **AI**：DeepSeek（对话/计划编排）+ 通义千问 Qwen-VL（看图评估）
- **前端（后台）**：Jinja2 + 原生 CSS/JS，设计系统见 `app/static/css/admin.css`
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
- **订阅与支付**：会员状态查看、手动开通 PRO（支付通道预留）
- **动作库**：按部位/器械/名称筛选，GIF 网格浏览

## 项目结构

```
app/
├── main.py                 # FastAPI 入口、路由与静态资源挂载
├── startup.py              # 建表、创建默认管理员
├── core/                   # 配置、安全(JWT/密码)、后台session
├── db/session.py           # SQLAlchemy 引擎与会话
├── models/                 # ORM 模型：Exercise/User/Plan/WorkoutLog...
├── schemas/                # Pydantic 请求/响应模型
├── services/               # 动作检索、后台统计
├── agent/                  # DeepSeek / Qwen-VL 客户端、计划生成器
├── api/
│   ├── deps.py             # 鉴权依赖
│   └── routes/             # auth / exercises / fitness / admin
├── templates/admin/        # 后台 Jinja2 页面
└── static/css/admin.css    # 后台设计系统
scripts/seed_exercises.py   # 动作数据导入
exercises-dataset/          # 原始 1324 动作数据集（原样保留）
```

## 后续阶段

- **P2**：Flutter App（登录、拍照评估、计划展示、跟练记录）
- **P3**：后台动作库 CRUD、更丰富的数据看板
- **P4**：会员权限校验接入接口、支付宝/微信与 App 内购
- **P5**：摄像头实时动作纠错（MediaPipe 姿态点 + 规则/模型）

## 安全与合规说明

- 所有 AI 评估均为初步参考，**不构成医学诊断**；"康复"仅做安全提示与就医建议。
- 默认 `JWT_SECRET`、管理员密码仅用于本地开发，生产环境务必替换。
- 用户上传的照片/视频存于 `app/static/uploads/`（已 gitignore）。
