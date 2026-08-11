# QA 测试基线

本文件记录 FormFit 后端 + App 的自动化测试运行方式、支付沙箱联调步骤与已知未覆盖项。
适用于 `ws-5-qa`（集成联调分支）及合入主干后的回归。

## 1. 后端测试（pytest）

### 运行环境

- Python 3.14（见 `.venv`），依赖在 `requirements.txt`
- 测试使用**内存 SQLite**，每个用例独立建表，不污染开发库 `formfit.db`
- DeepSeek / Qwen-VL 在测试中被 mock 或走保底路径，不需要真实 API key

### 全量执行

```bash
cd FormFit-integration
source .venv/bin/activate
python -m pytest -q
```

当前基线：**85 passed**（2026-08-11，`ws-5-qa`）。

### 测试文件分布

| 文件 | 覆盖范围 |
| --- | --- |
| `tests/test_e2e_journey.py` | 端到端闭环：注册→档案→评估→保底计划→计划详情→训练日志；真实 API 耗尽共享池；额度耗尽→沙箱支付→门控放行；后台越权；跨用户计划隔离 |
| `tests/test_membership_gate.py` | PRO 门控、免费共享额度池、跨月重置、PRO 不限次、过期 PRO 按 free 计 |
| `tests/test_payment.py` | 沙箱下单/回调/核销、伪造签名 401、篡改金额 400、重放幂等、连续购买顺延、恢复购买、跨用户票据拒付 |
| `tests/test_payment_channels.py` | 支付宝/微信渠道注册、缺凭证报错、RSA 验签成功/伪造/篡改金额、微信 AES-GCM 解密与时间戳防重放、端到端核销幂等 |
| `tests/test_hardening.py` | 默认密钥生产启动拦截、CORS 白名单、上传真实验型/大小限制/HEIC 转码、限流 429 + Retry-After、XFF 信任开关、已鉴权接口按 user 维度限流、后台 session 独立密钥与吊销 |

### 单文件 / 单用例

```bash
python -m pytest tests/test_e2e_journey.py -v
python -m pytest tests/test_payment.py::test_replay_callback_is_idempotent -v
```

## 2. App 测试（Flutter）

```bash
cd FormFit-integration/formfit_app
export PATH="/Users/apple/flutter/bin:$PATH"   # 或把 flutter 加入 PATH
flutter pub get
flutter analyze
flutter test
```

当前基线（2026-08-11）：

- `flutter analyze`：**1 warning** —— `assets/images/` 目录在 `pubspec.yaml` 中声明但不存在。
  代码中未引用该目录，属非功能性配置告警；建议后续要么补一个 `.gitkeep` 并放入实际图片，要么移除声明。
- `flutter test`：**27 passed**。

## 3. 支付沙箱联调

沙箱渠道不需要任何外部凭证，用 `SANDBOX_SECRET` 做 HMAC-SHA256 验签，适合本地/CI 端到端验证。

### 3.1 配置

`.env`：

```
PAYMENT_CHANNELS=sandbox
SANDBOX_SECRET=<任意强随机串>
```

### 3.2 下单 → 回调闭环

1. App / 脚本调用 `POST /api/payment/orders`，body：
   ```json
   { "plan_code": "pro_monthly", "channel": "sandbox" }
   ```
   返回 `order_no` 与 `pay_credential.sandbox.txn_id`、`amount_cents`。
2. 渠道服务器（联调时用脚本模拟）POST `/api/payment/callback/sandbox`：
   ```json
   {
     "order_no": "<order_no>",
     "txn_id": "<txn_id>",
     "status": "success",
     "amount_cents": 2800,
     "currency": "CNY"
   }
   ```
   签名头 `X-Sandbox-Signature` = `HMAC_SHA256(secret, "<order_no>.success.<amount_cents>.<txn_id>")`（hex）。
3. 服务端验签 → 比对订单金额 → 核销 → 开通会员（30 天）。
4. App 重新拉 `GET /api/membership` 即看到 `is_pro=true`、`quota.remaining=null`。

### 3.3 恢复购买

`POST /api/payment/restore`，body：

```json
{ "channel": "sandbox", "receipt_data": "<txn_id>:<product_id>:<sig>" }
```

其中 `<sig>` = `HMAC_SHA256(secret, "<txn_id>.<product_id>")`（hex），
`<product_id>` 需与套餐 `provider_product_id.sandbox` 一致。同一票据重复提交幂等；
票据已绑定他人时返回 401。

### 3.4 必须覆盖的负向用例

- 错误签名 / 缺失签名头 → 401
- 签名合法但 `amount_cents` 与订单不一致 → 400，会员不开通
- 同一成功回调重放 → 200，但 `expire_at` / `fulfilled_at` 不变
- A 用户的订单号用 B 的 token 查 → 404
- 沙箱票据伪造 / 已绑定他人 → 401

以上均已在 `tests/test_payment.py` 自动化。

## 4. 共享额度（免费用户）

- 免费用户体态评估与 AI 计划生成**共享**每月 5 次池（`FREE_QUOTA_PER_MONTH`，UTC 自然月）。
- 门控在业务处理**前**查询，本次成功后记录自然入账；超额返回 `402 quota_exhausted`，
  响应体带 `feature / limit / used / reset_at / upgrade_hint`，响应头带 `X-Quota-*` 快照。
- PRO 用户 `remaining=null`，不返回 `X-Quota-Remaining`。
- 跨月重置：本月之前的 `body_assessments` / `plans` 记录不计入本月计数
  （见 `test_membership_gate.py::test_quota_resets_across_months`）。

## 5. 手测清单（发布前人工过一遍）

真机/模拟器上按顺序走：

1. **注册登录**：新邮箱注册 → 自动登录进入主页；错误密码提示；停用账号登录被拒。
2. **建档**：填性别/年龄/身高/体重/目标/训练频率，保存后重开 App 仍在。
3. **体态评估**：拍一张或选一张照片 → 出评估结果（需配真实 Qwen-VL key 才出真实结果；
   未配置时服务端记录但 summary 为 mock 文案）。
4. **生成计划**：评估后点"生成计划" → 出训练日列表，每个动作有 GIF/中文步骤。
5. **额度用尽**：免费用户连续 5 次评估/计划后，第 6 次弹出付费墙（402 拦截）。
6. **沙箱购买**：付费墙选沙箱套餐 → "支付" → 会员态刷新 → 评估/计划不再被拦。
7. **恢复购买**：杀掉 App 重进 → 会员态仍为 pro；点"恢复购买"返回已开通。
8. **门控拦截**：会员过期后（可后台改 `expire_at`）功能重新锁定。
9. **后台**：未登录访问 `/admin` 跳登录页；普通用户 token 不能访问 `/admin/*`。

## 6. 已知未覆盖项（需真机 / 真实凭证 / 人工验证）

| 项 | 原因 | 建议验证方式 |
| --- | --- | --- |
| Apple IAP 真机购买/恢复 | 需 Apple 开发者账号 + 真机 + StoreKit 配置 | 沙箱账号在真机上走完整购买/恢复/断线重连 |
| 支付宝 / 微信真实回调 | 需要商户凭证与公网可访问的回调 URL | 沙箱联调环境填入真实 `.env`，用官方沙箱 App 扫码 |
| 真实 Qwen-VL 输出质量 | 评估结果的准确性、安全性、不当图片处理 | 收集 20+ 张真实体态照片人工评阅 |
| 真实 DeepSeek 计划质量 | 保底计划覆盖了流程，但 AI 分化计划的动作选择/容量合理性需人工评估 | 配真实 key 后让教练/资深训练者评审多份计划 |
| HEIC 真机拍照上传 | iOS 真机实拍 HEIC 的转码链路在模拟器上无法完整复现 | 真机拍 HEIC → 上传 → 确认落盘为 JPEG 且评估成功 |
| 限流在多进程/多副本下的表现 | 测试用的是内存限流，生产若用多 worker 需共享存储（如 redis） | 部署前确认 `slowapi` 存储后端与 worker 模型匹配 |
| 并发下单 / 并发回调 | 自动化为串行；同一订单并发回调的竞态需压测 | 用并发脚本对同一 `order_no` 同时打回调，验证核销幂等 |
| 邮件/推送等外发通知 | 本阶段未实现 | — |

## 7. 常见问题

- **`pytest` 报 `OperationalError: unable to open database file`**：测试默认用内存 SQLite，
  不应出现；若出现说明被 `.env` 中的 `DATABASE_URL` 覆盖，检查环境变量。
- **限流在测试中误触发 429**：`conftest.py` 有 `autouse` 夹具每个用例重置限流器；
  若在同一用例内需要高频调用，注意各接口阈值（注册 10/min、登录 20/min、下单 30/min）。
- **`flutter test` 报 `assets/images/` 找不到**：这是 `flutter analyze` 的 warning，
  不影响测试执行；若 CI 把 warning 当失败需在 `pubspec.yaml` 暂时移除该声明。
