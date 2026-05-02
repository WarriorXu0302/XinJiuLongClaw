"""
/api/mall/admin/orders/*

ERP 管理员端点（用 ERP CurrentUser + require_role）：
  GET  /                      列表（支持多种过滤）
  GET  /{order_id}            详情
  POST /{order_id}/reassign   强制改派
  POST /{order_id}/cancel     管理员取消
  POST /{order_id}/confirm-payment  财务确认收款 → 触发 commission
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.order import (
    MallOrder,
    MallOrderClaimLog,
    MallOrderItem,
    MallPayment,
    MallShipment,
)
from app.models.mall.user import MallUser
from app.services.audit_service import log_audit
from app.services.mall import inventory_service, order_service

router = APIRouter()


# =============================================================================
# 列表
# =============================================================================

@router.get("")
async def list_orders(
    user: CurrentUser,
    status: Optional[str] = Query(default=None, description="精确状态过滤"),
    order_no: Optional[str] = Query(default=None, description="订单号模糊"),
    customer_keyword: Optional[str] = Query(default=None, description="客户昵称/手机号"),
    assigned_salesman_id: Optional[str] = None,
    referrer_salesman_id: Optional[str] = None,
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """商城订单列表（管理员视角）。"""
    require_role(user, "admin", "boss", "finance")
    stmt = select(MallOrder)

    if status:
        stmt = stmt.where(MallOrder.status == status)
    if order_no:
        stmt = stmt.where(MallOrder.order_no.ilike(f"%{order_no}%"))
    if assigned_salesman_id:
        stmt = stmt.where(MallOrder.assigned_salesman_id == assigned_salesman_id)
    if referrer_salesman_id:
        stmt = stmt.where(MallOrder.referrer_salesman_id == referrer_salesman_id)
    if date_from:
        try:
            df = datetime.fromisoformat(date_from)
            stmt = stmt.where(MallOrder.created_at >= df)
        except ValueError:
            raise HTTPException(status_code=400, detail="date_from 格式应为 YYYY-MM-DD")
    if date_to:
        try:
            # 包含当天 → 加 1 天
            from datetime import timedelta
            dt = datetime.fromisoformat(date_to) + timedelta(days=1)
            stmt = stmt.where(MallOrder.created_at < dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="date_to 格式应为 YYYY-MM-DD")

    # 客户关键字：查 MallUser.nickname / phone + 地址 snapshot 里的 mobile
    if customer_keyword:
        kw = f"%{customer_keyword}%"
        cust_ids = [
            u.id for u in (await db.execute(
                select(MallUser).where(
                    (MallUser.nickname.ilike(kw)) | (MallUser.phone.ilike(kw))
                )
            )).scalars().all()
        ]
        if not cust_ids:
            return {"records": [], "total": 0}
        stmt = stmt.where(MallOrder.user_id.in_(cust_ids))

    total = int((await db.execute(
        select(sa_func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    stmt = stmt.order_by(desc(MallOrder.created_at)).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    if not rows:
        return {"records": [], "total": 0}

    # 批量关联 user + items 摘要
    user_ids = list({u for r in rows for u in [r.user_id, r.assigned_salesman_id, r.referrer_salesman_id] if u})
    users = (await db.execute(
        select(MallUser).where(MallUser.id.in_(user_ids))
    )).scalars().all()
    user_map = {u.id: u for u in users}

    order_ids = [r.id for r in rows]
    items = (await db.execute(
        select(MallOrderItem).where(MallOrderItem.order_id.in_(order_ids))
    )).scalars().all()
    items_by_order: dict[str, list] = {}
    for it in items:
        items_by_order.setdefault(it.order_id, []).append(it)

    def _brief(items_list):
        parts = []
        for it in items_list[:2]:
            snap = it.sku_snapshot or {}
            name = snap.get("product_name") or snap.get("sku_name") or ""
            parts.append(f"{name}×{it.quantity}")
        if len(items_list) > 2:
            parts.append(f"等{len(items_list)}件")
        return "，".join(parts)

    records = []
    for r in rows:
        cust = user_map.get(r.user_id)
        assigned = user_map.get(r.assigned_salesman_id) if r.assigned_salesman_id else None
        referrer = user_map.get(r.referrer_salesman_id) if r.referrer_salesman_id else None
        records.append({
            "id": r.id,
            "order_no": r.order_no,
            "status": r.status,
            "payment_status": r.payment_status,
            "total_amount": str(r.total_amount),
            "pay_amount": str(r.pay_amount),
            "received_amount": str(r.received_amount or 0),
            "customer": {"id": cust.id, "nickname": cust.nickname, "phone": cust.phone} if cust else None,
            "assigned_salesman": {"id": assigned.id, "nickname": assigned.nickname} if assigned else None,
            "referrer_salesman": {"id": referrer.id, "nickname": referrer.nickname} if referrer else None,
            "items_brief": _brief(items_by_order.get(r.id, [])),
            "created_at": r.created_at,
            "claimed_at": r.claimed_at,
            "shipped_at": r.shipped_at,
            "delivered_at": r.delivered_at,
            "completed_at": r.completed_at,
            "cancelled_at": r.cancelled_at,
            "remarks": r.remarks,
            "cancellation_reason": r.cancellation_reason,
        })
    return {"records": records, "total": total}


# =============================================================================
# 详情
# =============================================================================

@router.get("/{order_id}")
async def get_order(
    order_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "finance")
    order = await db.get(MallOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")

    items = (await db.execute(
        select(MallOrderItem).where(MallOrderItem.order_id == order.id)
    )).scalars().all()

    payments = (await db.execute(
        select(MallPayment)
        .where(MallPayment.order_id == order.id)
        .order_by(desc(MallPayment.created_at))
    )).scalars().all()

    shipments = (await db.execute(
        select(MallShipment).where(MallShipment.order_id == order.id)
    )).scalars().all()

    claim_logs = (await db.execute(
        select(MallOrderClaimLog)
        .where(MallOrderClaimLog.order_id == order.id)
        .order_by(desc(MallOrderClaimLog.created_at))
    )).scalars().all()

    # 人名 map
    user_ids = {order.user_id}
    if order.assigned_salesman_id: user_ids.add(order.assigned_salesman_id)
    if order.referrer_salesman_id: user_ids.add(order.referrer_salesman_id)
    user_ids |= {p.uploaded_by_user_id for p in payments if p.uploaded_by_user_id}
    user_ids |= {l.from_salesman_id for l in claim_logs if l.from_salesman_id}
    user_ids |= {l.to_salesman_id for l in claim_logs if l.to_salesman_id}
    users = (await db.execute(
        select(MallUser).where(MallUser.id.in_(user_ids))
    )).scalars().all()
    user_map = {u.id: u for u in users}

    def _u(uid):
        u = user_map.get(uid) if uid else None
        return {"id": u.id, "nickname": u.nickname, "phone": u.phone} if u else None

    return {
        "id": order.id,
        "order_no": order.order_no,
        "status": order.status,
        "payment_status": order.payment_status,
        "total_amount": str(order.total_amount),
        "shipping_fee": str(order.shipping_fee),
        "discount_amount": str(order.discount_amount),
        "pay_amount": str(order.pay_amount),
        "received_amount": str(order.received_amount or 0),
        "address": order.address_snapshot,
        "customer": _u(order.user_id),
        "assigned_salesman": _u(order.assigned_salesman_id),
        "referrer_salesman": _u(order.referrer_salesman_id),
        "items": [
            {
                "product_id": it.product_id,
                "sku_id": it.sku_id,
                "brand_id": it.brand_id,
                "sku_snapshot": it.sku_snapshot,
                "price": str(it.price),
                "quantity": it.quantity,
                "subtotal": str(it.subtotal),
                "cost_price_snapshot": str(it.cost_price_snapshot) if it.cost_price_snapshot else None,
            }
            for it in items
        ],
        "payments": [
            {
                "id": p.id,
                "amount": str(p.amount),
                "payment_method": p.payment_method,
                "channel": p.channel,
                "status": p.status,
                "confirmed_at": p.confirmed_at,
                "rejected_reason": p.rejected_reason,
                "uploaded_by": _u(p.uploaded_by_user_id),
                "created_at": p.created_at,
            }
            for p in payments
        ],
        "shipments": [
            {
                "id": s.id,
                "warehouse_id": s.warehouse_id,
                "status": s.status,
                "shipped_at": s.shipped_at,
                "delivered_at": s.delivered_at,
            }
            for s in shipments
        ],
        "claim_logs": [
            {
                "id": l.id,
                "action": l.action,
                "from_salesman": _u(l.from_salesman_id),
                "to_salesman": _u(l.to_salesman_id),
                "operator_id": l.operator_id,
                "operator_type": l.operator_type,
                "reason": l.reason,
                "created_at": l.created_at,
            }
            for l in claim_logs
        ],
        "created_at": order.created_at,
        "claimed_at": order.claimed_at,
        "shipped_at": order.shipped_at,
        "delivered_at": order.delivered_at,
        "paid_at": order.paid_at,
        "completed_at": order.completed_at,
        "cancelled_at": order.cancelled_at,
        "remarks": order.remarks,
        "cancellation_reason": order.cancellation_reason,
        "commission_posted": order.commission_posted,
        "profit_ledger_posted": order.profit_ledger_posted,
    }


# =============================================================================
# 取消（管理员权限，不限状态；已完成/已取消除外）
# =============================================================================

class _CancelBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


@router.post("/{order_id}/cancel")
async def admin_cancel(
    order_id: str,
    body: _CancelBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """管理员取消订单。

    允许取消：pending_assignment / assigned / shipped / delivered
    不允许：completed / cancelled / partial_closed（已结算，走退货/冲红流程）

    效果：
      · 订单 → cancelled，记 reason
      · 如果已扣库存（assigned/shipped/delivered），退回
      · 已 OUTBOUND 条码 → 改回 IN_STOCK
      · pending 凭证 → 全部 rejected
      · 通知业务员 + 消费者
    """
    from app.models.mall.base import (
        MallInventoryBarcodeStatus,
        MallOrderStatus,
        MallPaymentApprovalStatus,
    )
    from app.models.mall.inventory import MallInventoryBarcode

    require_role(user, "admin", "boss")
    # FOR UPDATE 锁订单，防与业务员并发 ship/deliver 相撞
    order = (await db.execute(
        select(MallOrder).where(MallOrder.id == order_id).with_for_update()
    )).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    prev_status = order.status  # 记真正的原状态，别被后面 L382 覆盖成 cancelled
    if order.status in (
        MallOrderStatus.COMPLETED.value,
        MallOrderStatus.CANCELLED.value,
        MallOrderStatus.PARTIAL_CLOSED.value,
        MallOrderStatus.REFUNDED.value,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"订单状态 {order.status} 不可取消（已完成订单走退货/冲红）",
        )

    # 退库存（只有真扣了的才退）。按原出库 flow 的 inventory 定位目标仓，不靠当前默认仓
    already_deducted = order.status in (
        MallOrderStatus.PENDING_ASSIGNMENT.value,
        MallOrderStatus.ASSIGNED.value,
        MallOrderStatus.SHIPPED.value,
        MallOrderStatus.DELIVERED.value,
        MallOrderStatus.PENDING_PAYMENT_CONFIRMATION.value,
    )
    restocked_count = 0
    if already_deducted:
        from app.models.mall.base import MallInventoryFlowType
        from app.models.mall.inventory import MallInventory, MallInventoryFlow
        items = await order_service.get_order_items(db, order.id)
        flows = (await db.execute(
            select(MallInventoryFlow, MallInventory)
            .join(MallInventory, MallInventoryFlow.inventory_id == MallInventory.id)
            .where(MallInventoryFlow.ref_type == "order")
            .where(MallInventoryFlow.ref_id == order.id)
            .where(MallInventoryFlow.flow_type == MallInventoryFlowType.OUT.value)
        )).all()
        sku_to_warehouse = {inv.sku_id: inv.warehouse_id for _, inv in flows}
        for it in items:
            src_wh = sku_to_warehouse.get(it.sku_id)
            if src_wh is None:
                raise HTTPException(
                    status_code=500,
                    detail=f"找不到 SKU {it.sku_id} 的原出库流水，无法退回",
                )
            await inventory_service.restock_for_cancel(
                db,
                warehouse_id=src_wh,
                sku_id=it.sku_id,
                quantity=it.quantity,
                order_id=order.id,
                cost_price=it.cost_price_snapshot,
            )
            restocked_count += it.quantity

    # 已扫码出库的条码 → 回 in_stock（用 outbound_order_id 反查）
    bcs = (await db.execute(
        select(MallInventoryBarcode)
        .where(MallInventoryBarcode.outbound_order_id == order.id)
        .where(MallInventoryBarcode.status == MallInventoryBarcodeStatus.OUTBOUND.value)
    )).scalars().all()
    for b in bcs:
        b.status = MallInventoryBarcodeStatus.IN_STOCK.value
        b.outbound_order_id = None
        b.outbound_by_user_id = None
        b.outbound_at = None

    # pending 凭证全部驳回
    pending_payments = (await db.execute(
        select(MallPayment)
        .where(MallPayment.order_id == order.id)
        .where(MallPayment.status == MallPaymentApprovalStatus.PENDING_CONFIRMATION.value)
    )).scalars().all()
    for p in pending_payments:
        p.status = MallPaymentApprovalStatus.REJECTED.value
        p.rejected_reason = f"订单被管理员取消：{body.reason}"

    order.status = MallOrderStatus.CANCELLED.value
    order.cancellation_reason = body.reason
    order.cancelled_at = datetime.now(timezone.utc)

    await log_audit(
        db, action="mall_order.admin_cancel", entity_type="MallOrder",
        entity_id=order.id,
        changes={
            "order_no": order.order_no,
            "prev_status": prev_status,  # 原状态，非覆盖后的 cancelled
            "reason": body.reason,
            "restocked_quantity": restocked_count,
            "barcodes_reverted": len(bcs),
            "pending_payments_rejected": len(pending_payments),
        },
        user=user, request=request,
    )
    await db.flush()

    # 通知
    from app.services.notification_service import notify_mall_user
    if order.assigned_salesman_id:
        await notify_mall_user(
            db, mall_user_id=order.assigned_salesman_id,
            title="订单已被管理员取消",
            content=f"订单 {order.order_no} 被管理员取消：{body.reason}",
            entity_type="MallOrder", entity_id=order.id,
        )
    await notify_mall_user(
        db, mall_user_id=order.user_id,
        title="订单已取消",
        content=f"您的订单 {order.order_no} 已取消：{body.reason}",
        entity_type="MallOrder", entity_id=order.id,
    )
    await db.flush()
    return {"order_no": order.order_no, "status": order.status}


# =============================================================================
# 辅助：可选业务员列表（改派下拉用）
# =============================================================================

@router.get("/_helpers/salesmen")
async def list_salesmen_for_reassign(
    user: CurrentUser,
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "finance")
    stmt = select(MallUser).where(MallUser.user_type == "salesman").where(MallUser.status == "active")
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(
            (MallUser.nickname.ilike(kw)) | (MallUser.phone.ilike(kw)) | (MallUser.username.ilike(kw))
        )
    stmt = stmt.order_by(MallUser.created_at).limit(50)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "records": [
            {"id": u.id, "nickname": u.nickname, "phone": u.phone, "username": u.username}
            for u in rows
        ]
    }


class _ReassignBody(BaseModel):
    target_salesman_user_id: str
    reason: Optional[str] = None


@router.post("/{order_id}/reassign")
async def reassign(
    order_id: str,
    body: _ReassignBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    # admin 端走 ERP get_db（admin session，不过 RLS），但我们操作 mall_* 表；
    # mall_* 表没 RLS 策略，read/write 正常
    order = await order_service.admin_reassign(
        db, order_id,
        target_salesman_id=body.target_salesman_user_id,
        operator_erp_user_id=user["sub"],
        reason=body.reason,
        request=request,
        actor_employee_id=user.get("employee_id"),
    )
    return {"order_no": order.order_no, "status": order.status,
            "assigned_salesman_id": order.assigned_salesman_id}


@router.post("/{order_id}/confirm-payment")
async def confirm_payment(
    order_id: str,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "finance")
    employee_id = user.get("employee_id")
    if not employee_id:
        raise HTTPException(status_code=400, detail="操作员没有关联 employee 记录")
    order = await order_service.confirm_payment(
        db, order_id, operator_employee_id=employee_id, request=request,
    )
    return {
        "order_no": order.order_no,
        "status": order.status,
        "payment_status": order.payment_status,
        "received_amount": str(order.received_amount),
        "pay_amount": str(order.pay_amount),
        "commission_posted": order.commission_posted,
    }
