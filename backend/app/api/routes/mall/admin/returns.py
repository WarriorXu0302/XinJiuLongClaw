"""
/api/mall/admin/returns/*

商城退货审批（admin/boss/finance 可操作）：
  GET  /                      列表（按 status tab 过滤）
  GET  /{id}                  详情（含订单信息 + 商品明细）
  POST /{id}/approve          批准退货（退库存 + 订单→refunded + commission 回写）
  POST /{id}/reject           驳回
  POST /{id}/mark-refunded    资金已到账，标记 refunded 完结
"""
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.order import MallOrder, MallReturnRequest
from app.models.mall.user import MallUser
from app.services.audit_service import log_audit
from app.services.mall import return_service

router = APIRouter()


def _return_dict(req: MallReturnRequest, order: Optional[MallOrder] = None, customer: Optional[MallUser] = None) -> dict:
    return {
        "id": req.id,
        "order_id": req.order_id,
        "order_no": order.order_no if order else None,
        "order_pay_amount": str(order.pay_amount) if order and order.pay_amount else None,
        "order_received_amount": str(order.received_amount) if order and order.received_amount else None,
        "customer": {
            "id": customer.id,
            "nickname": customer.nickname,
            "real_name": customer.real_name,
            "phone": customer.contact_phone or customer.phone,
        } if customer else None,
        "reason": req.reason,
        "status": req.status,
        "reviewer_employee_id": req.reviewer_employee_id,
        "reviewed_at": req.reviewed_at,
        "review_note": req.review_note,
        "refund_amount": str(req.refund_amount) if req.refund_amount else None,
        "refunded_at": req.refunded_at,
        "refund_method": req.refund_method,
        "refund_note": req.refund_note,
        "created_at": req.created_at,
    }


@router.get("")
async def list_returns(
    user: CurrentUser,
    status: Optional[str] = Query(default=None, pattern="^(pending|approved|refunded|rejected|all)$"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "finance")
    stmt = select(MallReturnRequest)
    if status and status != "all":
        stmt = stmt.where(MallReturnRequest.status == status)

    total = int((
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar() or 0)

    rows = (await db.execute(
        stmt.order_by(desc(MallReturnRequest.created_at)).offset(skip).limit(limit)
    )).scalars().all()
    if not rows:
        return {"records": [], "total": 0}

    # 批量查订单 + 客户
    order_ids = list({r.order_id for r in rows})
    user_ids = list({r.user_id for r in rows})
    orders = {o.id: o for o in (await db.execute(
        select(MallOrder).where(MallOrder.id.in_(order_ids))
    )).scalars().all()}
    users = {u.id: u for u in (await db.execute(
        select(MallUser).where(MallUser.id.in_(user_ids))
    )).scalars().all()}

    return {
        "records": [
            _return_dict(r, orders.get(r.order_id), users.get(r.user_id))
            for r in rows
        ],
        "total": total,
    }


@router.get("/{req_id}")
async def get_return(
    req_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "finance")
    req = await db.get(MallReturnRequest, req_id)
    if req is None:
        raise HTTPException(status_code=404, detail="退货申请不存在")
    order = await db.get(MallOrder, req.order_id)
    customer = await db.get(MallUser, req.user_id) if req.user_id else None
    d = _return_dict(req, order, customer)
    # 补商品明细
    from app.services.mall.order_service import get_order_items
    items = await get_order_items(db, req.order_id) if order else []
    d["items"] = [
        {
            "sku_id": it.sku_id,
            "product_name": (it.sku_snapshot or {}).get("product_name"),
            "sku_name": (it.sku_snapshot or {}).get("sku_name"),
            "price": str(it.price),
            "quantity": it.quantity,
            "subtotal": str(it.subtotal),
        }
        for it in items
    ]
    return d


class _ApproveBody(BaseModel):
    refund_amount: Optional[Decimal] = Field(default=None, ge=0)
    note: Optional[str] = Field(default=None, max_length=500)


@router.post("/{req_id}/approve")
async def approve(
    req_id: str,
    body: _ApproveBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """批准退货：退库存 + 订单→refunded + commission 标 reversed。"""
    require_role(user, "admin", "boss", "finance")
    req = await db.get(MallReturnRequest, req_id)
    if req is None:
        raise HTTPException(status_code=404, detail="退货申请不存在")

    updated = await return_service.approve_return(
        db, req=req,
        reviewer_employee_id=user.get("employee_id"),
        refund_amount=body.refund_amount,
        review_note=body.note,
    )
    await log_audit(
        db, action="mall_return.approve", entity_type="MallReturnRequest",
        entity_id=req.id, user=user, request=request,
        changes={
            "order_id": req.order_id,
            "refund_amount": str(updated.refund_amount) if updated.refund_amount else None,
            "note": body.note,
        },
    )

    # 通知消费者 + 配送业务员
    from app.services.notification_service import notify_mall_user
    order = await db.get(MallOrder, req.order_id)
    await notify_mall_user(
        db, mall_user_id=req.user_id,
        title="退货申请已通过",
        content=f"您对订单 {order.order_no if order else ''} 的退货申请已通过，预计退款金额 ¥{updated.refund_amount}，等待财务打款。",
        # 通知关联 order.id 让小程序点击能跳订单详情（MallReturnRequest 无对应 C 端页面）
        entity_type="MallOrder", entity_id=(order.id if order else req.order_id),
    )
    if order and order.assigned_salesman_id:
        await notify_mall_user(
            db, mall_user_id=order.assigned_salesman_id,
            title="您配送的订单发生退货",
            content=f"订单 {order.order_no} 已通过退货申请，相关提成已回写。",
            # 通知关联 order.id 让小程序点击能跳订单详情（MallReturnRequest 无对应 C 端页面）
        entity_type="MallOrder", entity_id=(order.id if order else req.order_id),
        )
    return _return_dict(updated, order)


class _RejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/{req_id}/reject")
async def reject(
    req_id: str,
    body: _RejectBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "finance")
    req = await db.get(MallReturnRequest, req_id)
    if req is None:
        raise HTTPException(status_code=404, detail="退货申请不存在")

    updated = await return_service.reject_return(
        db, req=req,
        reviewer_employee_id=user.get("employee_id"),
        review_note=body.reason,
    )
    await log_audit(
        db, action="mall_return.reject", entity_type="MallReturnRequest",
        entity_id=req.id, user=user, request=request,
        changes={"order_id": req.order_id, "reason": body.reason},
    )

    # 通知消费者
    from app.services.notification_service import notify_mall_user
    order = await db.get(MallOrder, req.order_id)
    await notify_mall_user(
        db, mall_user_id=req.user_id,
        title="退货申请未通过",
        content=f"您对订单 {order.order_no if order else ''} 的退货申请未通过，原因：{body.reason}",
        # 通知关联 order.id 让小程序点击能跳订单详情（MallReturnRequest 无对应 C 端页面）
        entity_type="MallOrder", entity_id=(order.id if order else req.order_id),
    )
    return _return_dict(updated, order)


class _MarkRefundedBody(BaseModel):
    refund_method: str = Field(pattern="^(cash|bank|wechat|alipay)$")
    refund_amount: Optional[Decimal] = Field(default=None, ge=0)
    note: Optional[str] = Field(default=None, max_length=500)


@router.post("/{req_id}/mark-refunded")
async def mark_refunded(
    req_id: str,
    body: _MarkRefundedBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """财务线下打款完成后标记 refunded，完结流程。"""
    require_role(user, "admin", "boss", "finance")
    req = await db.get(MallReturnRequest, req_id)
    if req is None:
        raise HTTPException(status_code=404, detail="退货申请不存在")

    updated = await return_service.mark_refunded(
        db, req=req,
        refund_method=body.refund_method,
        refund_note=body.note,
        refund_amount=body.refund_amount,
    )
    await log_audit(
        db, action="mall_return.mark_refunded", entity_type="MallReturnRequest",
        entity_id=req.id, user=user, request=request,
        changes={
            "refund_method": body.refund_method,
            "refund_amount": str(updated.refund_amount) if updated.refund_amount else None,
            "note": body.note,
        },
    )

    # 通知消费者
    from app.services.notification_service import notify_mall_user
    order = await db.get(MallOrder, req.order_id)
    await notify_mall_user(
        db, mall_user_id=req.user_id,
        title="退款已到账",
        content=f"您对订单 {order.order_no if order else ''} 的退款（¥{updated.refund_amount}）已完成，请查收。",
        # 通知关联 order.id 让小程序点击能跳订单详情（MallReturnRequest 无对应 C 端页面）
        entity_type="MallOrder", entity_id=(order.id if order else req.order_id),
    )
    return _return_dict(updated, order)
