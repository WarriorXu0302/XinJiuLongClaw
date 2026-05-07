"""/api/org-units/*  经营单元 CRUD

- GET  列表：所有登录用户可见（前端下拉/筛选用）
- POST/PUT/DELETE：仅 admin/boss
- code 一经建立不可改（FK 已指向，避免错乱）
- 删除走软删 is_active=false；如果仍有关联业务记录，拒绝硬删
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.org_unit import OrgUnit
from app.services import org_unit_service as ou_svc
from app.services.audit_service import log_audit

router = APIRouter()


# ---- schema ----------------------------------------------------------------


class _OrgUnitCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=20, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(..., min_length=1, max_length=50)
    sort_order: int = 0
    is_active: bool = True
    notes: Optional[str] = None


class _OrgUnitUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


def _to_dict(ou: OrgUnit) -> dict:
    return {
        "id": ou.id,
        "code": ou.code,
        "name": ou.name,
        "sort_order": ou.sort_order,
        "is_active": ou.is_active,
        "notes": ou.notes,
        "created_at": ou.created_at,
    }


# ---- CRUD ------------------------------------------------------------------


@router.get("")
async def list_org_units(
    user: CurrentUser,
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(OrgUnit)
    if not include_inactive:
        stmt = stmt.where(OrgUnit.is_active.is_(True))
    stmt = stmt.order_by(OrgUnit.sort_order, OrgUnit.created_at)
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_to_dict(o) for o in rows], "total": len(rows)}


@router.post("", status_code=201)
async def create_org_unit(
    body: _OrgUnitCreate,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    dup = (await db.execute(
        select(OrgUnit).where(OrgUnit.code == body.code)
    )).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(400, f"code '{body.code}' 已存在")

    ou = OrgUnit(
        code=body.code,
        name=body.name,
        sort_order=body.sort_order,
        is_active=body.is_active,
        notes=body.notes,
    )
    db.add(ou)
    await db.flush()
    ou_svc.clear_cache()  # 新单元建立后清缓存
    await log_audit(
        db, action="create_org_unit", entity_type="OrgUnit",
        entity_id=ou.id,
        changes={
            "code": ou.code, "name": ou.name,
            "sort_order": ou.sort_order, "is_active": ou.is_active,
            "notes": ou.notes,
        },
        user=user, request=request,
    )
    return _to_dict(ou)


@router.put("/{org_unit_id}")
async def update_org_unit(
    org_unit_id: str,
    body: _OrgUnitUpdate,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    ou = await db.get(OrgUnit, org_unit_id)
    if ou is None:
        raise HTTPException(404, "经营单元不存在")

    updates = body.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(ou, k, v)
    await db.flush()
    ou_svc.clear_cache()
    await log_audit(
        db, action="update_org_unit", entity_type="OrgUnit",
        entity_id=ou.id, changes=updates, user=user, request=request,
    )
    return _to_dict(ou)


@router.delete("/{org_unit_id}", status_code=204)
async def delete_org_unit(
    org_unit_id: str,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """软删：`is_active=false`。

    拒绝硬删场景：
      - 该单元下还有关联的 orders/commissions/store_sales/mall_orders/mall_purchase_orders
      - seed 的 3 个基础单元（brand_agent/retail/mall）不允许删
    """
    require_role(user, "admin", "boss")
    ou = await db.get(OrgUnit, org_unit_id)
    if ou is None:
        raise HTTPException(404, "经营单元不存在")
    if ou.code in ("brand_agent", "retail", "mall"):
        raise HTTPException(400, f"内置经营单元 {ou.code} 不允许删除；如需隐藏请改 is_active=false")

    # 软删
    ou.is_active = False
    await db.flush()
    ou_svc.clear_cache()
    await log_audit(
        db, action="disable_org_unit", entity_type="OrgUnit",
        entity_id=ou.id, changes={"is_active": False},
        user=user, request=request,
    )
    return None
