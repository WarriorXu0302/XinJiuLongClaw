"""
/api/mall/admin/payments/*

财务审批中心商城凭证管理。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
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
    """财务审批中心：待确认的商城收款凭证。

    返回字段补全为前端表格直接可用：
      - order_no / pay_amount / received_amount：财务看应收 vs 已确认 vs 本次凭证
      - salesman: {nickname, phone}：知道找谁追凭证
      - customer: {nickname, mobile}：电话回访核实
      - voucher_urls: list[{url, sha256, file_size}]：所有凭证图
      - remarks：上传时的备注
    """
    from app.models.mall.base import MallAttachmentType
    from app.models.mall.order import MallAttachment
    from app.models.mall.user import MallUser

    require_role(user, "admin", "boss", "finance")
    stmt = (
        select(MallPayment)
        .where(MallPayment.status == MallPaymentApprovalStatus.PENDING_CONFIRMATION.value)
        .order_by(desc(MallPayment.created_at))
    )
    total = int((await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    rows = (await db.execute(stmt.offset(skip).limit(limit))).scalars().all()

    if not rows:
        return {"records": [], "total": 0}

    # 批量拉关联：order / salesman / customer / voucher
    order_ids = list({p.order_id for p in rows})
    payment_ids = [p.id for p in rows]
    uploader_ids = list({p.uploaded_by_user_id for p in rows})

    orders = (await db.execute(
        select(MallOrder).where(MallOrder.id.in_(order_ids))
    )).scalars().all()
    order_map = {o.id: o for o in orders}

    customer_ids = list({o.user_id for o in orders})
    users = (await db.execute(
        select(MallUser).where(MallUser.id.in_(set(uploader_ids) | set(customer_ids)))
    )).scalars().all()
    user_map = {u.id: u for u in users}

    attachments = (await db.execute(
        select(MallAttachment)
        .where(MallAttachment.kind == MallAttachmentType.PAYMENT_VOUCHER.value)
        .where(MallAttachment.ref_type == "payment")
        .where(MallAttachment.ref_id.in_(payment_ids))
        .order_by(MallAttachment.created_at)
    )).scalars().all()
    atts_by_payment: dict[str, list] = {}
    for a in attachments:
        atts_by_payment.setdefault(a.ref_id, []).append({
            "url": a.file_url,
            "sha256": a.sha256,
            "file_size": a.file_size,
            "mime_type": a.mime_type,
        })

    records = []
    for p in rows:
        order = order_map.get(p.order_id)
        salesman = user_map.get(p.uploaded_by_user_id)
        customer = user_map.get(order.user_id) if order else None
        records.append({
            "id": p.id,
            "order_id": p.order_id,
            "order_no": order.order_no if order else None,
            "pay_amount": str(order.pay_amount) if order and order.pay_amount is not None else None,
            "received_amount": str(order.received_amount) if order and order.received_amount is not None else "0",
            "payment_amount": str(p.amount),
            "payment_method": p.payment_method,
            "channel": p.channel,
            "salesman": ({
                "id": salesman.id,
                "nickname": salesman.nickname,
                "phone": salesman.phone,
            } if salesman else None),
            "customer": ({
                "nickname": customer.nickname,
                "mobile": (order.address_snapshot or {}).get("mobile") if order else None,
            } if customer else None),
            "voucher_urls": atts_by_payment.get(p.id, []),
            "order_status": order.status if order else None,
            "created_at": p.created_at,
        })
    return {"records": records, "total": total}


class _RejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/{payment_id}/reject")
async def reject(
    payment_id: str,
    body: _RejectBody,
    user: CurrentUser,
    request: Request,
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
    # 注意：当前这条 p 在内存里已改成 REJECTED 但还没 flush，查询时要排除它的 id
    order = await db.get(MallOrder, p.order_id)
    if order and order.status == "pending_payment_confirmation":
        remaining = (await db.execute(
            select(MallPayment)
            .where(MallPayment.order_id == order.id)
            .where(MallPayment.id != p.id)
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
        user=user, request=request,
        changes={"order_id": p.order_id, "amount": str(p.amount), "reason": body.reason},
    )
    await db.flush()

    # 通知业务员
    if p.uploaded_by_user_id:
        from app.services.notification_service import notify_mall_user
        # entity_type=MallOrder 让小程序通知点击能直接跳订单详情页（MallPayment 无对应页面）
        # 订单号放 content 里让业务员一眼看到是哪单
        order_no = order.order_no if order else p.order_id
        await notify_mall_user(
            db, mall_user_id=p.uploaded_by_user_id,
            title="收款凭证被驳回",
            content=f"您上传的订单 {order_no} 凭证被驳回：{body.reason}",
            entity_type="MallOrder",
            entity_id=order.id if order else p.order_id,
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
    request: Request,
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
        # 始终以全款到账时刻为 completed_at（不再用 "if not"，避免 partial_closed 老时间被保留）
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
        user=user, request=request,
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
