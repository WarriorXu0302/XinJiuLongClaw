"""
/api/mall/workspace/store-returns/*

店员小程序端发起退货：
  - POST /            发起退货（必须是本店的已完成单）
  - GET /my           店员查自己发起的退货流水

权限：mall_user.user_type='salesman' + assigned_store_id 非空
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.base import WarehouseType
from app.models.product import Warehouse
from app.models.store_sale import StoreSaleReturn
from app.services import store_return_service
from app.services.mall import auth_service


router = APIRouter()


async def _require_cashier(current, db: AsyncSession):
    user = await auth_service.verify_token_and_load_user(db, current)
    if user.user_type != "salesman":
        raise HTTPException(status_code=403, detail="仅店员可访问")
    if not user.assigned_store_id:
        raise HTTPException(status_code=403, detail="您不是门店店员")
    if not user.linked_employee_id:
        raise HTTPException(status_code=400, detail="账号未绑定员工记录")
    store = await db.get(Warehouse, user.assigned_store_id)
    if store is None or store.warehouse_type != WarehouseType.STORE.value:
        raise HTTPException(status_code=400, detail="归属门店仓非法")
    if not store.is_active:
        raise HTTPException(status_code=400, detail=f"门店 {store.name} 已停用")
    return user


class _ApplyBody(BaseModel):
    original_sale_id: str
    reason: Optional[str] = Field(default=None, max_length=500)


@router.post("")
async def apply_my_return(
    body: _ApplyBody,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_cashier(current, db)
    ret = await store_return_service.apply_return(
        db,
        initiator_employee_id=user.linked_employee_id,
        original_sale_id=body.original_sale_id,
        reason=body.reason,
    )
    return {
        "return_no": ret.return_no,
        "status": ret.status,
        "refund_amount": str(ret.refund_amount),
        "total_bottles": ret.total_bottles,
    }


@router.get("/my")
async def list_my_returns(
    current: CurrentMallUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_cashier(current, db)
    stmt = (
        select(StoreSaleReturn)
        .where(StoreSaleReturn.initiator_employee_id == user.linked_employee_id)
        .order_by(desc(StoreSaleReturn.created_at))
    )
    total = int((await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar() or 0)
    rows = (await db.execute(stmt.offset(skip).limit(limit))).scalars().all()
    return {
        "records": [
            {
                "id": r.id,
                "return_no": r.return_no,
                "original_sale_id": r.original_sale_id,
                "status": r.status,
                "refund_amount": str(r.refund_amount),
                "total_bottles": r.total_bottles,
                "reason": r.reason,
                "rejection_reason": r.rejection_reason,
                "created_at": r.created_at,
                "reviewed_at": r.reviewed_at,
            }
            for r in rows
        ],
        "total": total,
    }
