"""
Supplier API routes — CRUD for suppliers/manufacturers.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.product import Supplier
from app.services.audit_service import log_audit

router = APIRouter()


class SupplierCreate(BaseModel):
    code: str
    name: str
    type: str = "supplier"
    brand_id: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    category: Optional[str] = None
    tax_no: Optional[str] = None
    bank: Optional[str] = None
    account_no: Optional[str] = None
    credit_limit: float = 0.0
    status: str = "active"


class SupplierUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    brand_id: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    category: Optional[str] = None
    tax_no: Optional[str] = None
    bank: Optional[str] = None
    account_no: Optional[str] = None
    credit_limit: Optional[float] = None
    status: Optional[str] = None


class SupplierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    code: str
    name: str
    type: str
    brand_id: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    category: Optional[str] = None
    tax_no: Optional[str] = None
    bank: Optional[str] = None
    account_no: Optional[str] = None
    credit_limit: float = 0.0
    status: str = "active"


@router.post("", response_model=SupplierResponse, status_code=201)
async def create_supplier(body: SupplierCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = Supplier(id=str(uuid.uuid4()), **body.model_dump())
    db.add(obj)
    await db.flush()
    return obj


@router.get("")
async def list_suppliers(
    user: CurrentUser,
    type: str | None = Query(None),
    brand_id: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    base = select(Supplier)
    if type:
        base = base.where(Supplier.type == type)
    if brand_id:
        base = base.where(Supplier.brand_id == brand_id)
    if status:
        base = base.where(Supplier.status == status)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(Supplier.name).offset(skip).limit(limit))).scalars().all()
    return {"items": rows, "total": total}


@router.get("/{supplier_id}", response_model=SupplierResponse)
async def get_supplier(supplier_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Supplier, supplier_id)
    if obj is None:
        raise HTTPException(404, "Supplier not found")
    return obj


@router.put("/{supplier_id}", response_model=SupplierResponse)
async def update_supplier(
    supplier_id: str, body: SupplierUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    obj = await db.get(Supplier, supplier_id)
    if obj is None:
        raise HTTPException(404, "Supplier not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return obj


@router.delete("/{supplier_id}", status_code=204)
async def delete_supplier(supplier_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "warehouse")
    obj = await db.get(Supplier, supplier_id)
    if obj is None:
        raise HTTPException(404, "Supplier not found")
    await db.delete(obj)
    await db.flush()
