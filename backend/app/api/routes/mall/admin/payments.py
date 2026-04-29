"""
/api/mall/admin/payments/*

财务审批中心商城凭证管理。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.base import MallPaymentApprovalStatus
from app.models.mall.order import MallOrder, MallPayment
from app.services.audit_service import log_audit

router = APIRouter()


@router.get("/pending")
async def list_pending(
    user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "finance")
    stmt = (
        select(MallPayment)
        .where(MallPayment.status == MallPaymentApprovalStatus.PENDING_CONFIRMATION.value)
        .order_by(desc(MallPayment.created_at))
    )
    rows = (await db.execute(stmt.offset(skip).limit(limit))).scalars().all()
    return {
        "records": [
            {
                "id": p.id,
                "order_id": p.order_id,
                "amount": str(p.amount),
                "payment_method": p.payment_method,
                "uploaded_by_user_id": p.uploaded_by_user_id,
                "created_at": p.created_at,
            }
            for p in rows
        ]
    }


class _RejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/{payment_id}/reject")
async def reject(
    payment_id: str,
    body: _RejectBody,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "finance")
    p = await db.get(MallPayment, payment_id)
    if p is None:
        raise HTTPException(status_code=404, detail="凭证不存在")
    if p.status != MallPaymentApprovalStatus.PENDING_CONFIRMATION.value:
        raise HTTPException(status_code=409, detail=f"凭证状态 {p.status} 不可驳回")

    p.status = MallPaymentApprovalStatus.REJECTED.value
    p.rejected_reason = body.reason

    # 如果订单所有 pending 凭证都被驳回 → 状态回到 delivered 等重传
    order = await db.get(MallOrder, p.order_id)
    if order and order.status == "pending_payment_confirmation":
        remaining = (await db.execute(
            select(MallPayment)
            .where(MallPayment.order_id == order.id)
            .where(MallPayment.status == MallPaymentApprovalStatus.PENDING_CONFIRMATION.value)
        )).scalars().all()
        if not remaining:
            order.status = "delivered"
            order.payment_status = "unpaid" if (order.received_amount or 0) == 0 else "partially_paid"

    await log_audit(
        db,
        action="mall_payment.reject",
        entity_type="MallPayment",
        entity_id=p.id,
        user=user,
        changes={"order_id": p.order_id, "amount": str(p.amount), "reason": body.reason},
    )
    await db.flush()

    # 通知业务员
    if p.uploaded_by_user_id:
        from app.services.notification_service import notify_mall_user
        await notify_mall_user(
            db, mall_user_id=p.uploaded_by_user_id,
            title="收款凭证被驳回",
            content=f"您上传的订单 {p.order_id} 凭证被驳回：{body.reason}",
            entity_type="MallPayment", entity_id=p.id,
        )

    return {"id": p.id, "status": p.status}


# =============================================================================
# Admin 手动补录收款（partial_closed 恢复 / 业务员无法操作时）
# =============================================================================

class _ManualPaymentBody(BaseModel):
    amount: float
    payment_method: str = Field(pattern="^(cash|bank|wechat|alipay)$")
    remarks: Optional[str] = Field(default=None, max_length=500)


@router.post("/manual-record/{order_id}")
async def manual_record_payment(
    order_id: str,
    body: _ManualPaymentBody,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Admin 补录线下收款。适用场景：
      - partial_closed 订单客户又来付剩余款项
      - 财务积压导致业务员凭证超期被驳，需人工补录

    流程：建 MallPayment(confirmed) + 累加 received + 幂等触发 commission。
    """
    require_role(user, "admin", "boss", "finance")
    # FOR UPDATE 锁订单，防并发补录
    order = (await db.execute(
        select(MallOrder).where(MallOrder.id == order_id).with_for_update()
    )).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status not in (
        "delivered", "pending_payment_confirmation", "partial_closed",
    ):
        raise HTTPException(
            status_code=409,
            detail=f"订单状态 {order.status} 不支持补录收款",
        )

    from decimal import Decimal
    import uuid
    amount = Decimal(str(body.amount)).quantize(Decimal("0.01"))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于 0")

    # 上限：补款后合计不得超过 pay_amount * 1.05（容 5% 溢出做抹零/手续费）
    projected = (order.received_amount or Decimal("0")) + amount
    max_allowed = order.pay_amount * Decimal("1.05")
    if projected > max_allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"补录金额超出应收上限（应收 {order.pay_amount}，"
                f"已收 {order.received_amount or 0}，本次 {amount}）"
            ),
        )

    employee_id = user.get("employee_id")

    now = datetime.now(timezone.utc)
    payment = MallPayment(
        id=str(uuid.uuid4()),
        order_id=order.id,
        uploaded_by_user_id=order.assigned_salesman_id or order.referrer_salesman_id or order.user_id,
        amount=amount,
        payment_method=body.payment_method,
        channel="offline",
        status=MallPaymentApprovalStatus.CONFIRMED.value,
        confirmed_at=now,
        confirmed_by_employee_id=employee_id,
        remarks=f"Admin 补录：{body.remarks or ''}",
    )
    db.add(payment)

    order.received_amount = (order.received_amount or Decimal("0")) + amount

    from app.services.mall.commission_service import post_commission_for_order

    from app.services.notification_service import notify_mall_user

    if order.received_amount >= order.pay_amount and order.status != "completed":
        order.status = "completed"
        order.payment_status = "fully_paid"
        order.paid_at = now
        if not order.completed_at:
            order.completed_at = now
        await db.flush()
        await post_commission_for_order(db, order)
        # 通知 consumer + salesman（补录完成订单）
        await notify_mall_user(
            db, mall_user_id=order.user_id,
            title="订单已完成",
            content=f"订单补录收款已确认，交易完成。",
            entity_type="MallOrder", entity_id=order.id,
        )
        if order.assigned_salesman_id:
            await notify_mall_user(
                db, mall_user_id=order.assigned_salesman_id,
                title="订单完结（管理员补录）",
                content=f"订单由管理员补录收款完结，提成已入账。",
                entity_type="MallOrder", entity_id=order.id,
            )
    else:
        await db.flush()

    await log_audit(
        db,
        action="mall_payment.manual_record",
        entity_type="MallOrder",
        entity_id=order.id,
        user=user,
        changes={
            "amount": str(amount),
            "method": body.payment_method,
            "received_after": str(order.received_amount),
            "status_after": order.status,
        },
    )
    return {
        "order_id": order.id,
        "status": order.status,
        "received_amount": str(order.received_amount),
        "commission_posted": order.commission_posted,
    }
