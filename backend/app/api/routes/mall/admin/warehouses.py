"""
/api/mall/admin/warehouses/*

mall_warehouses CRUD。manager_user_id 必须指向 user_type='salesman' 的 mall_user。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.mall.user import MallUser
from app.models.mall.inventory import MallWarehouse
from app.services.audit_service import log_audit

router = APIRouter()


class _WarehouseCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    address: Optional[str] = None
    manager_user_id: Optional[str] = None
    is_active: bool = True


class _WarehouseUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    manager_user_id: Optional[str] = None
    is_active: Optional[bool] = None


def _to_dict(w: MallWarehouse) -> dict:
    return {
        "id": w.id,
        "code": w.code,
        "name": w.name,
        "address": w.address,
        "manager_user_id": w.manager_user_id,
        "is_active": w.is_active,
        "created_at": w.created_at,
        "updated_at": w.updated_at,
    }


async def _assert_manager_is_salesman(db: AsyncSession, user_id: Optional[str]) -> None:
    """manager_user_id 必须指向 user_type='salesman' 的 mall_user（应用层前置校验 + DB 触发器兜底）。"""
    if user_id is None:
        return
    u = await db.get(MallUser, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="指定的仓库管理员不存在")
    if u.user_type != "salesman":
        raise HTTPException(
            status_code=400,
            detail=f"仓库管理员必须是业务员（当前 {u.user_type}）",
        )


@router.get("")
async def list_warehouses(
    user: CurrentUser,
    keyword: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "warehouse")
    stmt = select(MallWarehouse)
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(
            (MallWarehouse.code.ilike(kw)) | (MallWarehouse.name.ilike(kw))
        )
    if is_active is not None:
        stmt = stmt.where(MallWarehouse.is_active.is_(is_active))
    stmt = stmt.order_by(desc(MallWarehouse.created_at))
    rows = (await db.execute(stmt)).scalars().all()

    # 批量取经理 nickname
    mgr_ids = [w.manager_user_id for w in rows if w.manager_user_id]
    mgr_map: dict[str, dict] = {}
    if mgr_ids:
        mgrs = (await db.execute(
            select(MallUser).where(MallUser.id.in_(mgr_ids))
        )).scalars().all()
        mgr_map = {m.id: {"nickname": m.nickname, "phone": m.phone} for m in mgrs}

    return {
        "records": [
            {**_to_dict(w), "manager": mgr_map.get(w.manager_user_id)}
            for w in rows
        ]
    }


@router.get("/{warehouse_id}")
async def get_warehouse(
    warehouse_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "warehouse")
    w = await db.get(MallWarehouse, warehouse_id)
    if w is None:
        raise HTTPException(status_code=404, detail="仓库不存在")
    return _to_dict(w)


@router.post("", status_code=201)
async def create_warehouse(
    body: _WarehouseCreate,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    # code 唯一
    dup = (await db.execute(
        select(MallWarehouse).where(MallWarehouse.code == body.code)
    )).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=400, detail=f"仓库编码 {body.code} 已存在")

    await _assert_manager_is_salesman(db, body.manager_user_id)

    w = MallWarehouse(
        code=body.code,
        name=body.name,
        address=body.address,
        manager_user_id=body.manager_user_id,
        is_active=body.is_active,
    )
    db.add(w)
    await db.flush()
    await log_audit(
        db, action="create_mall_warehouse", entity_type="MallWarehouse",
        entity_id=w.id,
        changes={
            "code": w.code, "name": w.name, "address": w.address,
            "manager_user_id": w.manager_user_id, "is_active": w.is_active,
        },
        user=user, request=request,
    )
    return _to_dict(w)


@router.put("/{warehouse_id}")
async def update_warehouse(
    warehouse_id: str,
    body: _WarehouseUpdate,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    w = await db.get(MallWarehouse, warehouse_id)
    if w is None:
        raise HTTPException(status_code=404, detail="仓库不存在")

    updates = body.model_dump(exclude_unset=True)
    if "manager_user_id" in updates:
        await _assert_manager_is_salesman(db, updates["manager_user_id"])

    for k, v in updates.items():
        setattr(w, k, v)
    w.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await log_audit(
        db, action="update_mall_warehouse", entity_type="MallWarehouse",
        entity_id=w.id, changes=updates, user=user, request=request,
    )
    return _to_dict(w)


@router.delete("/{warehouse_id}", status_code=204)
async def delete_warehouse(
    warehouse_id: str,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """禁用仓库（软删）。硬删涉及 mall_inventory FK，改走 is_active=false。

    前置校验：
      - 仓里还有库存 → 拒绝（先盘出去再禁用；否则库存挂空无法复用）
      - 有该仓出库但还未完成的在途订单 → 拒绝
    """
    from sqlalchemy import func as sa_func
    from app.models.mall.base import MallOrderStatus
    from app.models.mall.inventory import MallInventory, MallInventoryFlow

    require_role(user, "admin", "boss")
    w = await db.get(MallWarehouse, warehouse_id)
    if w is None:
        raise HTTPException(status_code=404, detail="仓库不存在")
    if not w.is_active:
        return  # 幂等

    stock_qty = int((await db.execute(
        select(sa_func.coalesce(sa_func.sum(MallInventory.quantity), 0))
        .where(MallInventory.warehouse_id == warehouse_id)
    )).scalar() or 0)
    if stock_qty > 0:
        raise HTTPException(
            status_code=409,
            detail=f"仓内还有 {stock_qty} 件库存，请先盘出或调拨再禁用",
        )

    # 有该仓发出但还在途的订单（通过 flow→order join）
    in_flight = int((await db.execute(
        select(sa_func.count(MallOrder.id.distinct()))
        .select_from(MallInventoryFlow)
        .join(MallInventory, MallInventoryFlow.inventory_id == MallInventory.id)
        .join(MallOrder, MallOrder.id == MallInventoryFlow.ref_id)
        .where(MallInventory.warehouse_id == warehouse_id)
        .where(MallInventoryFlow.ref_type == "order")
        .where(MallOrder.status.in_([
            MallOrderStatus.PENDING_ASSIGNMENT.value,
            MallOrderStatus.ASSIGNED.value,
            MallOrderStatus.SHIPPED.value,
            MallOrderStatus.DELIVERED.value,
            MallOrderStatus.PENDING_PAYMENT_CONFIRMATION.value,
        ]))
    )).scalar() or 0)
    if in_flight > 0:
        raise HTTPException(
            status_code=409,
            detail=f"仓有 {in_flight} 笔在途订单未完成，禁用后无法按原仓退货",
        )

    w.is_active = False
    w.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await log_audit(
        db, action="disable_mall_warehouse", entity_type="MallWarehouse",
        entity_id=w.id, changes={"is_active": False}, user=user, request=request,
    )
