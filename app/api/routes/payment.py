"""支付路由：套餐目录、下单、订单状态、回调、恢复购买。

回调端点不做登录鉴权（由渠道服务器调用），安全完全依赖各渠道的验签；
其余接口均需 App 用户登录。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models import User
from app.payment import supported_channels
from app.payment.base import PaymentVerifyError
from app.schemas.payment import (
    OrderCreateIn,
    OrderOut,
    OrderStatusOut,
    PLAN_CATALOG,
    PlanOut,
    RestoreIn,
)
from app.services import payment_service
from app.services.payment_service import PaymentError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payment", tags=["payment"])


@router.get("/plans", response_model=list[PlanOut])
def list_plans(channel: str = "sandbox"):
    """供 FE-3 付费墙拉取套餐。可选 channel 参数返回该渠道商品 id。"""
    out = []
    for code, item in PLAN_CATALOG.items():
        pid = item.get("provider_product_id", {}).get(channel)
        out.append(
            PlanOut(
                plan_code=code,
                plan=item["plan"],
                title=item["title"],
                duration_days=item["duration_days"],
                amount_cents=item["amount_cents"],
                currency=item.get("currency", "CNY"),
                provider_product_id=pid,
            )
        )
    return out


@router.get("/channels")
def list_channels():
    return {"channels": supported_channels()}


@router.post("/orders", response_model=OrderOut)
@limiter.limit(settings.rate_limit_create_order)
def create_order(
    request: Request,
    body: OrderCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        order = payment_service.create_order(db, user, body.plan_code, body.channel)
        credential = payment_service.build_pay_credential(order)
    except PaymentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OrderOut(
        order_no=order.order_no,
        plan=order.plan,
        plan_code=order.plan_code,
        duration_days=order.duration_days,
        amount_cents=order.amount_cents,
        currency=order.currency,
        payment_channel=order.payment_channel,
        status=order.status,
        pay_credential=credential,
        created_at=order.created_at,
    )


@router.get("/orders/{order_no}", response_model=OrderStatusOut)
def get_order(
    order_no: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        order = payment_service.get_order(db, user, order_no)
    except PaymentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    view = payment_service.order_status_view(order, user)
    return OrderStatusOut(**view)


@router.post("/restore", response_model=OrderOut)
def restore_purchase(
    body: RestoreIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """App 内购恢复购买：提交渠道票据，服务端校验后开通/恢复会员。"""
    try:
        order = payment_service.restore_purchase(
            db, user, body.channel, body.receipt_data
        )
    except PaymentVerifyError as exc:
        # 验签失败 = 401，伪造票据不能开通
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except PaymentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OrderOut(
        order_no=order.order_no,
        plan=order.plan,
        plan_code=order.plan_code,
        duration_days=order.duration_days,
        amount_cents=order.amount_cents,
        currency=order.currency,
        payment_channel=order.payment_channel,
        status=order.status,
        pay_credential={},
        created_at=order.created_at,
    )


# ---------- 渠道异步回调（无登录鉴权，靠验签）----------
def _read_headers(request: Request) -> dict[str, str]:
    return {k.lower(): v for k, v in request.headers.items()}


@router.post("/callback/{channel}")
async def payment_callback(
    channel: str, request: Request, db: Session = Depends(get_db)
):
    body = await request.body()
    headers = _read_headers(request)
    try:
        payment_service.handle_callback(db, channel, headers, body)
    except PaymentVerifyError as exc:
        # 验签失败：返回 401，渠道通常不会重试（也不应成功）；安全记录
        logger.warning("支付回调验签失败 channel=%s err=%s", channel, exc)
        raise HTTPException(status_code=401, detail="invalid signature") from exc
    except PaymentError as exc:
        # 订单不存在等：返回 4xx，避免渠道无意义重放；但记录便于排查
        logger.warning("支付回调处理失败 channel=%s err=%s", channel, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 各渠道期望的成功应答不同；沙箱/通用返回 ok，真实渠道接入时在此按渠道适配
    return {"code": "ok", "channel": channel}
