"""支付相关 Pydantic 模型。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ---------- 套餐目录 ----------
# 首发套餐待产品最终定价；这里集中维护，供下单校验与 FE-3 拉取。
# 金额单位为“分”（整数）。provider_product_id 预留给各渠道商品 ID 映射。
PLAN_CATALOG: dict[str, dict[str, Any]] = {
    "pro_monthly": {
        "plan": "pro",
        "title": "Pro 月度会员",
        "duration_days": 30,
        "amount_cents": 2800,
        "currency": "CNY",
        "provider_product_id": {"apple": "formfit.pro.monthly"},
    },
    "pro_yearly": {
        "plan": "pro",
        "title": "Pro 年度会员",
        "duration_days": 365,
        "amount_cents": 19800,
        "currency": "CNY",
        "provider_product_id": {"apple": "formfit.pro.yearly"},
    },
}


class PlanOut(BaseModel):
    plan_code: str
    plan: str
    title: str
    duration_days: int
    amount_cents: int
    currency: str
    provider_product_id: str | None = None


class OrderCreateIn(BaseModel):
    plan_code: str = Field(..., description="套餐编码，见 /api/payment/plans")
    channel: str = Field("sandbox", description="支付渠道：sandbox/apple/...")


class OrderOut(BaseModel):
    order_no: str
    plan: str
    plan_code: str
    duration_days: int
    amount_cents: int
    currency: str
    payment_channel: str
    status: str
    # 渠道侧的支付凭据/参数：沙箱为直链，真实渠道为预下单串/支付参数
    pay_credential: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}


class OrderStatusOut(BaseModel):
    order_no: str
    status: str
    is_active: bool = Field(..., description="会员当前是否有效")
    expire_at: datetime | None = None


class RestoreIn(BaseModel):
    """App 内购恢复购买：客户端提交交易回执，由服务端校验并开通。"""
    channel: str = "apple"
    # Apple: base64 receipt；其他渠道：交易号/票据
    receipt_data: str = Field(..., min_length=1)


class QuotaOut(BaseModel):
    """免费档月度共享额度池状态（体态评估与 AI 计划生成共用同一池子）。"""

    scope: str = Field("shared", description="额度口径：shared=两功能共享同一池子")
    limit: int = Field(..., description="每月免费次数上限（共享池总额）")
    used: int = Field(..., description="本月已用次数（UTC 自然月，两功能之和）")
    remaining: int | None = Field(
        ..., description="剩余次数；PRO 用户为 null（不限次）"
    )
    reset_at: datetime = Field(..., description="额度重置时间（次月 1 日 UTC）")
    breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="本月已用次数按功能拆分，仅展示用（assess/generate_plan）",
    )


class MembershipOut(BaseModel):
    """当前用户会员态。供 App 在启动/支付完成后刷新权益与付费墙状态。"""

    plan: str = Field(..., description="free / pro")
    is_active: bool = Field(..., description="会员当前是否有效（已激活且未过期）")
    is_pro: bool = Field(..., description="有效且为 pro 套餐的便捷标志")
    expire_at: datetime | None = None
    payment_channel: str | None = None
    # 客户端据此判断是否展示付费墙/解锁被门控功能
    features_locked: bool = Field(
        ..., description="PRO 功能是否被锁定（true 时前端应弹付费墙）"
    )
    # 免费档月度共享额度池：体态评估与计划生成共用 5 次/月。
    quota: QuotaOut | None = Field(
        default=None, description="本月共享免费额度状态；PRO 用户 remaining=null"
    )

    model_config = {"from_attributes": True}
