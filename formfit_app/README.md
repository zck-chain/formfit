# FormFit App

FormFit 的 Flutter 移动端客户端，已接入真实后端。覆盖登录/注册、体态拍照评估、AI 训练计划生成与展示、跟练记录、身体档案六条核心链路。

## 技术栈

- Flutter 3.27+ / Dart 3.6
- 状态管理：`flutter_riverpod`
- 路由：`go_router`（登录守卫在 `lib/app.dart`）
- 网络：`dio`（JWT 注入 + 统一错误处理，见 `lib/api/api_client.dart`）
- 本地存储：`shared_preferences`（持久化 JWT）
- 视觉：「Night Energy / 能量霓虹」设计系统，cyber 组件位于 `lib/widgets/cyber/`

## 运行

```bash
cd formfit_app

# 安装依赖
flutter pub get

# 调试运行（默认连接 http://127.0.0.1:8000）
flutter run

# 指定后端地址
flutter run --dart-define=API_BASE_URL=http://192.168.x.x:8000
```

> Android 模拟器访问宿主机后端需用 `10.0.2.2`；iOS 模拟器用 `127.0.0.1`；真机用电脑局域网 IP。地址通过 `--dart-define=API_BASE_URL=...` 覆盖，见 `lib/core/config.dart`。

## 工程基线

```bash
flutter analyze   # 静态分析，要求 0 issue
flutter test      # 单元 / widget 测试
```

## 结构

```
lib/
├── main.dart                 # 入口，启动时恢复登录态
├── app.dart                  # MaterialApp + go_router + 登录守卫
├── core/config.dart          # API 地址与媒体 URL 拼接
├── api/
│   ├── api_client.dart       # Dio、TokenStore、统一 ApiException
│   └── repository.dart       # 后端数据访问层（鉴权/档案/评估/计划/记录）
├── models/                   # user / assessment / plan / exercise
├── providers/auth_provider.dart
├── theme/app_theme.dart      # 颜色、斜切角、主题
├── widgets/
│   ├── cyber/                # cyber_background / glow_button / hud_card
│   ├── badges.dart
│   └── exercise_image.dart   # 远程动图占位/失败态
└── features/
    ├── auth/                 # 登录 / 注册
    ├── home/                 # 首页、底部导航、计划 Tab、我的 Tab
    ├── assessment/           # 拍照体态评估
    ├── plan/                 # 计划列表、单日动作
    ├── workout/              # 跟练页（逐个动作 + 保存记录）
    └── profile/              # 身体档案编辑
```

## 依赖的后端接口（App 视角契约）

| 方法 | 路径 | 入参 | 返回 |
|---|---|---|---|
| POST | `/api/auth/register` | `email` `password` `nickname?` | `{ access_token, user }` |
| POST | `/api/auth/login` | `email` `password` | `{ access_token, user }` |
| GET | `/api/auth/me` | — | 当前 user |
| GET/PUT | `/api/fitness/profile` | 见 `UserProfile.toJson` | profile |
| POST | `/api/fitness/assess` | multipart `file` + 身高/体重/年龄/性别 | `Assessment` |
| POST | `/api/fitness/plans/generate` | 空 body | `Plan` |
| GET | `/api/fitness/plans` | — | `Plan[]` |
| POST | `/api/fitness/logs` | `title` `duration_min?` `sets[]` | — |

JWT 通过 `Authorization: Bearer <token>` 携带。模型字段以 `lib/models/` 为准；后端需保证计划 `content.days[].items[]` 至少包含 `exercise_id / name / gif_url / image / sets / reps`，否则跟练页会因缺动作给出空态。

## 已知边界 / 后续

- `generatePlan` 当前基于服务端档案编排，不直接接收体态评估结果；评估方向目前仅作用户参考。如需把评估结果纳入计划生成，属后端契约变更，需先在服务端扩展接口。
- 会员中心 / 隐私与安全为占位入口（SnackBar 提示开发中）。
- 媒体资源依赖后端可访问的 GIF/图片地址；`AppConfig.resolveUrl` 会把相对路径拼上后端 host。
