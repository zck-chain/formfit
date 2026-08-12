"""管理员操作审计事件模型。

与支付对账专用的 `payment_audit_events` 分离：本表记录 Web 后台管理员对用户/会员
的写操作（发放、收回、启停），用于留痕、追责与撤销依据。只存最小必要快照：
- before_json / after_json：仅记录被改动实体的关键字段（如 membership 的 plan/is_active/expire_at），
  绝不写入密码哈希、密钥、Cookie/Authorization 头等敏感数据。
- reason：人工发放/收回时必填的操作事由。
- request_id：关联结构化访问日志（app.main 中间件生成/透传 X-Request-ID）。
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# 管理员动作类型
ADMIN_ACTIONS = (
    "grant_membership",   # 发放/延长会员
    "revoke_membership",  # 收回会员
    "toggle_user",        # 启用/停用用户
)


class AdminAuditEvent(Base):
    __tablename__ = "admin_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # 操作者（管理员 user id）
    admin_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    # 被操作的目标用户 id
    target_user_id: Mapped[int] = mapped_column(Integer, index=True)

    # 改动前/后关键字段快照（白名单小 JSON，不含敏感数据）
    before_json: Mapped[dict] = mapped_column(JSON, default=dict)
    after_json: Mapped[dict] = mapped_column(JSON, default=dict)

    # 操作事由：发放/收回必填；启停可选
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 关联访问日志的 request_id（X-Request-ID），便于串联排查
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # 可选幂等键：客户端（后台表单/API）提交的 Idempotency-Key，用于短窗口去重。
    # 命中重复时不再执行业务改动，after_json 中记录 idempotency_replay=true。
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
