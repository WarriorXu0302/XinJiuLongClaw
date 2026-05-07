"""商城 / 门店采购路由（和 ERP B2B 采购分离）。

- scope='mall'：入 mall_warehouses + 付款扣 MALL_MASTER 账户
- scope='store'：入 warehouses(warehouse_type='store') + 付款扣 STORE_MASTER 账户
- 不受 brand_ids RLS 限制（mall/store 采购跨品牌）

状态机：pending → approved → paid → received → completed
        │         │         │
        └─ reject / cancel 分支随时可走

权限：
  - 创建：admin / boss / purchase / warehouse（店员也可建 store scope 单）
  - 审批：admin / boss（审批人必须是管理员，本规则由 Q3=b 决策）
  - 付款：admin / boss / finance
  - 收货：admin / boss / warehouse / purchase

本层只做参数校验 + 路由分发，所有业务写在 `mall_purchase_service`。
"""
from datetime import date as date_type
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall_purchase import MallPurchaseOrder, MallPurchaseOrderItem
from app.services import mall_purchase_service as svc
from app.services.audit_service import log_audit

router = APIRouter()


# =============================================================================
# Pydantic
# =============================================================================


class _POItemIn(BaseModel):
    mall_sku_id: int
    quantity: int = Field(..., gt=0)
    quantity_unit: str = "瓶"
    unit_price: float = Field(..., ge=0)


class _POCreateIn(BaseModel):
    scope: str = Field(..., pattern="^(mall|store)$")
    supplier_id: str
    # 按 scope 二选一，互斥；service 层再做一次校验
    mall_warehouse_id: Optional[str] = None
    store_warehouse_id: Optional[str] = None
    cash_account_id: Optional[str] = None  # 不传默认 MALL_MASTER / STORE_MASTER
    expected_date: Optional[date_type] = None
    notes: Optional[str] = None
    items: list[_POItemIn]


class _RejectIn(BaseModel):
    reason: str = Field(..., min_length=1)


class _CancelIn(BaseModel):
    reason: str = Field(..., min_length=1)


class _POItemOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    mall_sku_id: int
    quantity: int
    quantity_unit: str
    unit_price: float
    sku: Optional[Any] = None


class _POOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    po_no: str
    scope: str
    supplier_id: str
    supplier: Optional[Any] = None
    mall_warehouse_id: Optional[str] = None
    mall_warehouse: Optional[Any] = None
    store_warehouse_id: Optional[str] = None
    store_warehouse: Optional[Any] = None
    total_amount: float
    cash_amount: float
    cash_account_id: Optional[str] = None
    cash_account: Optional[Any] = None
    voucher_url: Optional[str] = None
    status: str
    operator_id: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    paid_by: Optional[str] = None
    paid_at: Optional[datetime] = None
    received_by: Optional[str] = None
    received_at: Optional[datetime] = None
    expected_date: Optional[date_type] = None
    notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    items: list[_POItemOut] = []


# =============================================================================
# 转换
# =============================================================================


def _to_response(po: MallPurchaseOrder) -> dict:
    d = _POOut.model_validate(po).model_dump()
    d["supplier"] = {"id": po.supplier.id, "name": po.supplier.name} if po.supplier else None
    d["mall_warehouse"] = (
        {"id": po.mall_warehouse.id, "name": po.mall_warehouse.name}
        if po.mall_warehouse else None
    )
    d["store_warehouse"] = (
        {"id": po.store_warehouse.id, "name": po.store_warehouse.name,
         "warehouse_type": po.store_warehouse.warehouse_type}
        if po.store_warehouse else None
    )
    d["cash_account"] = (
        {"id": po.cash_account.id, "name": po.cash_account.name,
         "code": po.cash_account.code, "balance": float(po.cash_account.balance)}
        if po.cash_account else None
    )
    d["items"] = []
    for it in po.items:
        item_d = _POItemOut.model_validate(it).model_dump()
        if it.sku:
            item_d["sku"] = {
                "id": it.sku.id,
                "spec": it.sku.spec,
                "barcode": it.sku.barcode,
            }
        d["items"].append(item_d)
    return d


# =============================================================================
# CRUD
# =============================================================================


@router.post("", status_code=201)
async def create_mall_po(
    body: _POCreateIn,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """建采购单（status=pending）。不扣款、不动库存。"""
    require_role(user, "admin", "boss", "purchase", "warehouse")

    po = await svc.create_po(
        db,
        scope=body.scope,
        supplier_id=body.supplier_id,
        mall_warehouse_id=body.mall_warehouse_id,
        store_warehouse_id=body.store_warehouse_id,
        items=[it.model_dump() for it in body.items],
        cash_account_id=body.cash_account_id,
        expected_date=body.expected_date,
        notes=body.notes,
        operator_id=user.get("employee_id"),
    )
    await db.refresh(po, ["items", "supplier", "mall_warehouse", "store_warehouse", "cash_account"])
    await log_audit(
        db,
        action="create_mall_purchase_order",
        entity_type="MallPurchaseOrder",
        entity_id=po.id,
        changes={
            "scope": po.scope, "supplier_id": po.supplier_id,
            "total_amount": float(po.total_amount),
            "items_count": len(po.items),
        },
        user=user, request=request,
    )
    return _to_response(po)


@router.get("")
async def list_mall_pos(
    user: CurrentUser,
    scope: Optional[str] = Query(None, pattern="^(mall|store)$"),
    status: Optional[str] = Query(None),
    supplier_id: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """列表，支持按 scope / status / supplier_id 过滤。"""
    require_role(user, "admin", "boss", "purchase", "warehouse", "finance")

    stmt = select(MallPurchaseOrder)
    if scope:
        stmt = stmt.where(MallPurchaseOrder.scope == scope)
    if status:
        stmt = stmt.where(MallPurchaseOrder.status == status)
    if supplier_id:
        stmt = stmt.where(MallPurchaseOrder.supplier_id == supplier_id)

    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar() or 0
    rows = (await db.execute(
        stmt.order_by(MallPurchaseOrder.created_at.desc())
            .offset(skip).limit(limit)
    )).scalars().all()

    return {"items": [_to_response(po) for po in rows], "total": total}


@router.get("/pending-approval")
async def list_pending_approval(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """审批中心聚合：待审批 pending 的商城/门店采购单。"""
    require_role(user, "admin", "boss")
    rows = (await db.execute(
        select(MallPurchaseOrder)
        .where(MallPurchaseOrder.status == "pending")
        .order_by(MallPurchaseOrder.created_at.desc())
    )).scalars().all()
    return {"items": [_to_response(po) for po in rows], "total": len(rows)}


@router.get("/{po_id}")
async def get_mall_po(
    po_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "purchase", "warehouse", "finance")
    po = await db.get(MallPurchaseOrder, po_id)
    if po is None:
        raise HTTPException(404, "采购单不存在")
    return _to_response(po)


# =============================================================================
# 审批流
# =============================================================================


@router.post("/{po_id}/approve")
async def approve(
    po_id: str,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """管理员批准（status: pending → approved）。不扣款。"""
    require_role(user, "admin", "boss")
    approver = user.get("employee_id")
    if not approver:
        raise HTTPException(400, "当前登录用户没有绑定 employee_id，无法审批")

    po = await svc.approve_po(db, po_id=po_id, approver_employee_id=approver)
    await db.refresh(po, ["items", "supplier", "mall_warehouse", "store_warehouse", "cash_account"])
    await log_audit(
        db, action="approve_mall_purchase_order",
        entity_type="MallPurchaseOrder", entity_id=po.id,
        changes={"status": "pending→approved"}, user=user, request=request,
    )
    return _to_response(po)


@router.post("/{po_id}/reject")
async def reject(
    po_id: str,
    body: _RejectIn,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """管理员驳回（status: pending → rejected）。"""
    require_role(user, "admin", "boss")
    reviewer = user.get("employee_id")
    if not reviewer:
        raise HTTPException(400, "当前登录用户没有绑定 employee_id，无法驳回")

    po = await svc.reject_po(
        db, po_id=po_id, reviewer_employee_id=reviewer, reason=body.reason,
    )
    await db.refresh(po, ["items", "supplier", "mall_warehouse", "store_warehouse", "cash_account"])
    await log_audit(
        db, action="reject_mall_purchase_order",
        entity_type="MallPurchaseOrder", entity_id=po.id,
        changes={"status": "pending→rejected", "reason": body.reason},
        user=user, request=request,
    )
    return _to_response(po)


@router.post("/{po_id}/pay")
async def pay(
    po_id: str,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """财务付款（status: approved → paid）。扣 MALL_MASTER / STORE_MASTER 账户余额。"""
    require_role(user, "admin", "boss", "finance")
    payer = user.get("employee_id")
    if not payer:
        raise HTTPException(400, "当前登录用户没有绑定 employee_id，无法付款")

    po = await svc.pay_po(db, po_id=po_id, payer_employee_id=payer)
    await db.refresh(po, ["items", "supplier", "mall_warehouse", "store_warehouse", "cash_account"])
    await log_audit(
        db, action="pay_mall_purchase_order",
        entity_type="MallPurchaseOrder", entity_id=po.id,
        changes={
            "status": "approved→paid",
            "amount": float(po.total_amount),
            "account_id": po.cash_account_id,
        },
        user=user, request=request,
    )
    return _to_response(po)


@router.post("/{po_id}/receive")
async def receive(
    po_id: str,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """仓管收货（status: paid → completed）。入库 + 更新加权平均成本。

    第一版仅支持 scope='mall'（入 mall_inventory）；scope='store' 返 501
    等业务确认门店仓底层归属后再扩展。
    """
    require_role(user, "admin", "boss", "warehouse", "purchase")
    receiver = user.get("employee_id")
    if not receiver:
        raise HTTPException(400, "当前登录用户没有绑定 employee_id，无法收货")

    po = await svc.receive_po(db, po_id=po_id, receiver_employee_id=receiver)
    await db.refresh(po, ["items", "supplier", "mall_warehouse", "store_warehouse", "cash_account"])
    await log_audit(
        db, action="receive_mall_purchase_order",
        entity_type="MallPurchaseOrder", entity_id=po.id,
        changes={"status": "paid→completed"}, user=user, request=request,
    )
    return _to_response(po)


@router.post("/{po_id}/cancel")
async def cancel(
    po_id: str,
    body: _CancelIn,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """取消采购单（仅 pending/approved 允许；paid 的需走退款流程，第一版不支持）。"""
    require_role(user, "admin", "boss", "purchase")
    po = await svc.cancel_po(db, po_id=po_id, reason=body.reason)
    await db.refresh(po, ["items", "supplier", "mall_warehouse", "store_warehouse", "cash_account"])
    await log_audit(
        db, action="cancel_mall_purchase_order",
        entity_type="MallPurchaseOrder", entity_id=po.id,
        changes={"status": f"→cancelled", "reason": body.reason},
        user=user, request=request,
    )
    return _to_response(po)
