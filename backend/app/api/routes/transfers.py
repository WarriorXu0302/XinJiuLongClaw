"""仓库调拨 API

端点：
  POST  /api/transfers                   创建（含扫码）
  POST  /api/transfers/{id}/submit       提交审批
  POST  /api/transfers/{id}/approve      审批通过
  POST  /api/transfers/{id}/reject       驳回
  POST  /api/transfers/{id}/execute      执行（条码过户 + 库存扣加）
  POST  /api/transfers/{id}/cancel       取消
  GET   /api/transfers                   列表（状态过滤）
  GET   /api/transfers/{id}              详情（含明细）
  GET   /api/transfers/pending-approval  审批中心用

权限：
  - 创建 / 取消：boss / warehouse / purchase
  - 审批 / 驳回：boss / finance
  - 执行：boss / warehouse（审批过的单子或免审的）
"""
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.inventory import MallWarehouse
from app.models.product import Warehouse
from app.models.transfer import (
    TRANSFER_STATUS_PENDING_APPROVAL,
    WAREHOUSE_SIDE_ERP,
    WAREHOUSE_SIDE_MALL,
    WarehouseTransfer,
    WarehouseTransferItem,
)
from app.services import transfer_service
from app.services.audit_service import log_audit

router = APIRouter()


# =============================================================================
# Schemas
# =============================================================================


class TransferCreateBody(BaseModel):
    source_side: str = Field(pattern="^(erp|mall)$")
    source_warehouse_id: str
    dest_side: str = Field(pattern="^(erp|mall)$")
    dest_warehouse_id: str
    barcodes: list[str] = Field(min_length=1)
    reason: Optional[str] = Field(default=None, max_length=1000)


class TransferRejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class TransferCancelBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


def _to_dict(t: WarehouseTransfer, *, with_items: bool = False,
             items: Optional[list[WarehouseTransferItem]] = None) -> dict:
    result: dict[str, Any] = {
        "id": t.id,
        "transfer_no": t.transfer_no,
        "source_side": t.source_side,
        "source_warehouse_id": t.source_warehouse_id,
        "dest_side": t.dest_side,
        "dest_warehouse_id": t.dest_warehouse_id,
        "status": t.status,
        "requires_approval": t.requires_approval,
        "initiator_employee_id": t.initiator_employee_id,
        "submitted_at": t.submitted_at,
        "approved_at": t.approved_at,
        "approver_employee_id": t.approver_employee_id,
        "rejection_reason": t.rejection_reason,
        "executed_at": t.executed_at,
        "cancelled_at": t.cancelled_at,
        "reason": t.reason,
        "total_bottles": t.total_bottles,
        "total_cost": str(t.total_cost) if t.total_cost is not None else None,
        "created_at": t.created_at,
    }
    if with_items and items is not None:
        result["items"] = [
            {
                "id": it.id,
                "barcode": it.barcode,
                "product_ref": it.product_ref,
                "sku_ref": it.sku_ref,
                "cost_price_snapshot": str(it.cost_price_snapshot) if it.cost_price_snapshot is not None else None,
                "batch_no_snapshot": it.batch_no_snapshot,
            }
            for it in items
        ]
    return result


async def _require_employee_id(user: dict) -> str:
    emp_id = user.get("employee_id")
    if not emp_id:
        raise HTTPException(
            status_code=403,
            detail="用户未绑定 employee，无法操作调拨",
        )
    return emp_id


# =============================================================================
# Create
# =============================================================================


@router.post("")
async def create_transfer(
    body: TransferCreateBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "warehouse", "purchase")
    emp_id = await _require_employee_id(user)

    t = await transfer_service.create_transfer(
        db,
        initiator_employee_id=emp_id,
        source_side=body.source_side,
        source_warehouse_id=body.source_warehouse_id,
        dest_side=body.dest_side,
        dest_warehouse_id=body.dest_warehouse_id,
        barcodes=body.barcodes,
        reason=body.reason,
    )
    await log_audit(
        db, action="warehouse_transfer.create",
        entity_type="WarehouseTransfer", entity_id=t.id,
        user=user, request=request,
        changes={
            "transfer_no": t.transfer_no,
            "source": f"{t.source_side}:{t.source_warehouse_id}",
            "dest": f"{t.dest_side}:{t.dest_warehouse_id}",
            "barcode_count": len(body.barcodes),
            "requires_approval": t.requires_approval,
            "total_cost": str(t.total_cost) if t.total_cost else None,
        },
    )
    return _to_dict(t)


# =============================================================================
# Submit / Approve / Reject / Cancel
# =============================================================================


@router.post("/{transfer_id}/submit")
async def submit(
    transfer_id: str,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "warehouse", "purchase")
    emp_id = await _require_employee_id(user)
    t = await transfer_service.submit_transfer(
        db, transfer_id=transfer_id, actor_employee_id=emp_id,
    )
    await log_audit(
        db, action="warehouse_transfer.submit",
        entity_type="WarehouseTransfer", entity_id=t.id,
        user=user, request=request,
        changes={"transfer_no": t.transfer_no},
    )
    return _to_dict(t)


@router.post("/{transfer_id}/approve")
async def approve(
    transfer_id: str,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "finance")
    emp_id = await _require_employee_id(user)
    t = await transfer_service.approve_transfer(
        db, transfer_id=transfer_id, approver_employee_id=emp_id,
    )
    await log_audit(
        db, action="warehouse_transfer.approve",
        entity_type="WarehouseTransfer", entity_id=t.id,
        user=user, request=request,
        changes={"transfer_no": t.transfer_no},
    )
    return _to_dict(t)


@router.post("/{transfer_id}/reject")
async def reject(
    transfer_id: str,
    body: TransferRejectBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "finance")
    emp_id = await _require_employee_id(user)
    t = await transfer_service.reject_transfer(
        db, transfer_id=transfer_id,
        approver_employee_id=emp_id, reason=body.reason,
    )
    await log_audit(
        db, action="warehouse_transfer.reject",
        entity_type="WarehouseTransfer", entity_id=t.id,
        user=user, request=request,
        changes={"transfer_no": t.transfer_no, "reason": body.reason},
    )
    return _to_dict(t)


@router.post("/{transfer_id}/cancel")
async def cancel(
    transfer_id: str,
    body: TransferCancelBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "warehouse", "purchase")
    emp_id = await _require_employee_id(user)
    t = await transfer_service.cancel_transfer(
        db, transfer_id=transfer_id, actor_employee_id=emp_id,
    )
    await log_audit(
        db, action="warehouse_transfer.cancel",
        entity_type="WarehouseTransfer", entity_id=t.id,
        user=user, request=request,
        changes={"transfer_no": t.transfer_no, "reason": body.reason},
    )
    return _to_dict(t)


@router.post("/{transfer_id}/execute")
async def execute(
    transfer_id: str,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "warehouse")
    emp_id = await _require_employee_id(user)
    t = await transfer_service.execute_transfer(
        db, transfer_id=transfer_id, actor_employee_id=emp_id,
    )
    await log_audit(
        db, action="warehouse_transfer.execute",
        entity_type="WarehouseTransfer", entity_id=t.id,
        user=user, request=request,
        changes={
            "transfer_no": t.transfer_no,
            "total_bottles": t.total_bottles,
            "source": f"{t.source_side}:{t.source_warehouse_id}",
            "dest": f"{t.dest_side}:{t.dest_warehouse_id}",
        },
    )
    return _to_dict(t)


# =============================================================================
# List / Detail
# =============================================================================


async def _enrich_with_wh_names(db: AsyncSession, records: list[dict]) -> list[dict]:
    """给 records 注入源/目标仓的 name，便于前端展示。"""
    erp_ids = {r["source_warehouse_id"] for r in records if r["source_side"] == "erp"}
    erp_ids |= {r["dest_warehouse_id"] for r in records if r["dest_side"] == "erp"}
    mall_ids = {r["source_warehouse_id"] for r in records if r["source_side"] == "mall"}
    mall_ids |= {r["dest_warehouse_id"] for r in records if r["dest_side"] == "mall"}

    erp_map = {}
    mall_map = {}
    if erp_ids:
        for w in (await db.execute(
            select(Warehouse).where(Warehouse.id.in_(erp_ids))
        )).scalars():
            erp_map[w.id] = w.name
    if mall_ids:
        for w in (await db.execute(
            select(MallWarehouse).where(MallWarehouse.id.in_(mall_ids))
        )).scalars():
            mall_map[w.id] = w.name

    for r in records:
        src_map = erp_map if r["source_side"] == "erp" else mall_map
        dst_map = erp_map if r["dest_side"] == "erp" else mall_map
        r["source_warehouse_name"] = src_map.get(r["source_warehouse_id"])
        r["dest_warehouse_name"] = dst_map.get(r["dest_warehouse_id"])
    return records


@router.get("")
async def list_transfers(
    user: CurrentUser,
    status: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "warehouse", "purchase", "finance")
    stmt = select(WarehouseTransfer)
    if status:
        stmt = stmt.where(WarehouseTransfer.status == status)
    total = int((await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    rows = (await db.execute(
        stmt.order_by(desc(WarehouseTransfer.created_at)).offset(skip).limit(limit)
    )).scalars().all()
    records = [_to_dict(t) for t in rows]
    records = await _enrich_with_wh_names(db, records)
    return {"records": records, "total": total}


@router.get("/pending-approval")
async def list_pending_approval(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """审批中心"仓库调拨待审" tab 用。"""
    require_role(user, "boss", "finance", "warehouse")
    rows = (await db.execute(
        select(WarehouseTransfer)
        .where(WarehouseTransfer.status == TRANSFER_STATUS_PENDING_APPROVAL)
        .order_by(desc(WarehouseTransfer.submitted_at))
    )).scalars().all()
    records = [_to_dict(t) for t in rows]
    records = await _enrich_with_wh_names(db, records)
    return {"records": records, "total": len(records)}


@router.get("/{transfer_id}")
async def get_transfer(
    transfer_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "warehouse", "purchase", "finance")
    t = await db.get(WarehouseTransfer, transfer_id)
    if t is None:
        raise HTTPException(status_code=404, detail="调拨单不存在")
    items = (await db.execute(
        select(WarehouseTransferItem).where(
            WarehouseTransferItem.transfer_id == transfer_id
        )
    )).scalars().all()
    d = _to_dict(t, with_items=True, items=items)
    await _enrich_with_wh_names(db, [d])
    return d
