"""
/api/store-returns/*

门店退货双端路由：
  - 管理端：/api/store-returns（GET 列表 / POST 新建 / approve / reject）
  - 小程序店员：/api/mall/workspace/store-returns（apply / list my）另起文件

权限：
  - GET / approve / reject：boss / finance / admin
  - POST（手动建）：boss / warehouse（极少用；正常流程是小程序发起）
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
from app.models.mall.user import MallUser
from app.models.product import Warehouse
from app.models.store_sale import (
    StoreSale,
    StoreSaleReturn,
    StoreSaleReturnItem,
)
from app.models.user import Employee
from app.services import store_return_service
from app.services.audit_service import log_audit

router = APIRouter()


# =============================================================================
# Schemas
# =============================================================================


class ApplyReturnBody(BaseModel):
    original_sale_id: str
    initiator_employee_id: str
    reason: Optional[str] = Field(default=None, max_length=500)


class RejectBody(BaseModel):
    rejection_reason: str = Field(min_length=1, max_length=500)


def _to_dict(r: StoreSaleReturn, *, with_items: bool = False,
             items: Optional[list[StoreSaleReturnItem]] = None) -> dict:
    d: dict[str, Any] = {
        "id": r.id,
        "return_no": r.return_no,
        "original_sale_id": r.original_sale_id,
        "store_id": r.store_id,
        "initiator_employee_id": r.initiator_employee_id,
        "customer_id": r.customer_id,
        "reason": r.reason,
        "status": r.status,
        "refund_amount": str(r.refund_amount),
        "commission_reversal_amount": str(r.commission_reversal_amount),
        "total_bottles": r.total_bottles,
        "reviewer_employee_id": r.reviewer_employee_id,
        "reviewed_at": r.reviewed_at,
        "rejection_reason": r.rejection_reason,
        "created_at": r.created_at,
    }
    if with_items and items is not None:
        d["items"] = [
            {
                "id": it.id,
                "original_item_id": it.original_item_id,
                "barcode": it.barcode,
                "product_id": it.product_id,
                "batch_no_snapshot": it.batch_no_snapshot,
                "sale_price_snapshot": str(it.sale_price_snapshot),
                "commission_reversal": str(it.commission_reversal),
            }
            for it in items
        ]
    return d


async def _enrich_list(db: AsyncSession, records: list[dict]) -> list[dict]:
    store_ids = list({r["store_id"] for r in records})
    emp_ids = list({r["initiator_employee_id"] for r in records})
    cust_ids = list({r["customer_id"] for r in records})
    sale_ids = list({r["original_sale_id"] for r in records})

    store_map = {}
    if store_ids:
        for w in (await db.execute(
            select(Warehouse).where(Warehouse.id.in_(store_ids))
        )).scalars():
            store_map[w.id] = w.name
    emp_map = {}
    if emp_ids:
        for e in (await db.execute(
            select(Employee).where(Employee.id.in_(emp_ids))
        )).scalars():
            emp_map[e.id] = e.name
    cust_map = {}
    if cust_ids:
        for c in (await db.execute(
            select(MallUser).where(MallUser.id.in_(cust_ids))
        )).scalars():
            cust_map[c.id] = c.real_name or c.nickname or c.username or c.id[:8]
    sale_map = {}
    if sale_ids:
        for s in (await db.execute(
            select(StoreSale).where(StoreSale.id.in_(sale_ids))
        )).scalars():
            sale_map[s.id] = s.sale_no

    for r in records:
        r["store_name"] = store_map.get(r["store_id"])
        r["initiator_name"] = emp_map.get(r["initiator_employee_id"])
        r["customer_name"] = cust_map.get(r["customer_id"])
        r["original_sale_no"] = sale_map.get(r["original_sale_id"])
    return records


# =============================================================================
# 列表 / 详情 / 审批
# =============================================================================


@router.get("")
async def list_returns(
    user: CurrentUser,
    status: Optional[str] = None,
    store_id: Optional[str] = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "finance", "admin", "warehouse")
    stmt = select(StoreSaleReturn)
    if status:
        stmt = stmt.where(StoreSaleReturn.status == status)
    if store_id:
        stmt = stmt.where(StoreSaleReturn.store_id == store_id)
    total = int((await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    rows = (await db.execute(
        stmt.order_by(desc(StoreSaleReturn.created_at)).offset(skip).limit(limit)
    )).scalars().all()
    records = [_to_dict(r) for r in rows]
    records = await _enrich_list(db, records)
    return {"records": records, "total": total}


@router.get("/pending-approval")
async def list_pending_approval(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """审批中心"门店退货待审" tab 用。"""
    require_role(user, "boss", "finance", "admin")
    rows = (await db.execute(
        select(StoreSaleReturn)
        .where(StoreSaleReturn.status == "pending")
        .order_by(desc(StoreSaleReturn.created_at))
    )).scalars().all()
    records = [_to_dict(r) for r in rows]
    records = await _enrich_list(db, records)
    return {"records": records, "total": len(records)}


@router.get("/{return_id}")
async def get_return(
    return_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "finance", "admin", "warehouse")
    r = await db.get(StoreSaleReturn, return_id)
    if r is None:
        raise HTTPException(status_code=404, detail="退货单不存在")
    items = (await db.execute(
        select(StoreSaleReturnItem).where(StoreSaleReturnItem.return_id == return_id)
    )).scalars().all()
    d = _to_dict(r, with_items=True, items=items)
    await _enrich_list(db, [d])
    return d


@router.post("")
async def apply_return(
    body: ApplyReturnBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """管理端手动建退货单（极少用，正常走小程序）。"""
    require_role(user, "boss", "warehouse")
    ret = await store_return_service.apply_return(
        db,
        initiator_employee_id=body.initiator_employee_id,
        original_sale_id=body.original_sale_id,
        reason=body.reason,
    )
    await log_audit(
        db, action="store_return.apply",
        entity_type="StoreSaleReturn", entity_id=ret.id,
        user=user, request=request,
        changes={
            "return_no": ret.return_no,
            "original_sale_id": body.original_sale_id,
            "initiator": body.initiator_employee_id,
            "refund_amount": str(ret.refund_amount),
            "bottles": ret.total_bottles,
        },
    )
    return _to_dict(ret)


@router.post("/{return_id}/approve")
async def approve(
    return_id: str,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "finance", "admin")
    emp_id = user.get("employee_id")
    if not emp_id:
        raise HTTPException(status_code=403, detail="用户未绑定 employee，无法审批")
    ret = await store_return_service.approve_return(
        db, return_id=return_id, reviewer_employee_id=emp_id,
    )
    await log_audit(
        db, action="store_return.approve",
        entity_type="StoreSaleReturn", entity_id=ret.id,
        user=user, request=request,
        changes={
            "return_no": ret.return_no,
            "refund_amount": str(ret.refund_amount),
            "commission_reversal": str(ret.commission_reversal_amount),
            "bottles": ret.total_bottles,
        },
    )
    return _to_dict(ret)


@router.post("/{return_id}/reject")
async def reject(
    return_id: str,
    body: RejectBody,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "finance", "admin")
    emp_id = user.get("employee_id")
    if not emp_id:
        raise HTTPException(status_code=403, detail="用户未绑定 employee，无法驳回")
    ret = await store_return_service.reject_return(
        db, return_id=return_id, reviewer_employee_id=emp_id,
        rejection_reason=body.rejection_reason,
    )
    await log_audit(
        db, action="store_return.reject",
        entity_type="StoreSaleReturn", entity_id=ret.id,
        user=user, request=request,
        changes={"return_no": ret.return_no, "reason": body.rejection_reason},
    )
    return _to_dict(ret)
