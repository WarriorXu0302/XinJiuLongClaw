"""
/api/mall/workspace/inspection-cases

业务员扫码稽查 — 列表 + 创建案件。
创建后 status='pending'，进 ERP 财务审批；小程序只做填报入口。
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.inspection import InspectionCase
from app.services.mall import auth_service

router = APIRouter()


async def _require_linked(current, db):
    user = await auth_service.verify_token_and_load_user(db, current)
    if user.user_type != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可访问")
    if not user.linked_employee_id:
        raise HTTPException(status_code=400, detail="业务员未绑定员工记录")
    return user


def _gen_no() -> str:
    return f"IC{datetime.now(timezone.utc).strftime('%Y%m%d')}{uuid.uuid4().hex[:6].upper()}"


@router.get("")
async def list_cases(
    current: CurrentMallUser,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_linked(current, db)
    stmt = select(InspectionCase).where(InspectionCase.found_by == user.linked_employee_id)
    if status:
        stmt = stmt.where(InspectionCase.status == status)
    stmt = stmt.order_by(desc(InspectionCase.created_at)).limit(100)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "records": [
            {
                "id": r.id,
                "case_no": r.case_no,
                "case_type": r.case_type,
                "barcode": r.barcode,
                "qrcode": r.qrcode,
                "batch_no": r.batch_no,
                "brand_id": r.brand_id,
                "product_id": r.product_id,
                "found_location": r.found_location,
                "found_time": r.found_time,
                "quantity": r.quantity,
                "quantity_unit": r.quantity_unit,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    }


class _CreateBody(BaseModel):
    case_type: str  # A1 / A2 / A3 / B1 / B2 / B3 等
    barcode: Optional[str] = None
    qrcode: Optional[str] = None
    batch_no: Optional[str] = None
    product_id: Optional[str] = None
    brand_id: Optional[str] = None
    found_location: Optional[str] = None
    quantity: int = 1
    quantity_unit: str = "瓶"
    original_sale_price: Optional[Decimal] = None


@router.post("")
async def create_case(
    body: _CreateBody,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_linked(current, db)
    rec = InspectionCase(
        id=str(uuid.uuid4()),
        case_no=_gen_no(),
        case_type=body.case_type,
        barcode=body.barcode,
        qrcode=body.qrcode,
        batch_no=body.batch_no,
        product_id=body.product_id,
        brand_id=body.brand_id,
        found_location=body.found_location,
        found_time=datetime.now(timezone.utc),
        found_by=user.linked_employee_id,
        quantity=body.quantity,
        quantity_unit=body.quantity_unit,
        original_sale_price=body.original_sale_price,
        status="pending",
    )
    db.add(rec)
    await db.flush()
    return {
        "id": rec.id,
        "case_no": rec.case_no,
        "status": rec.status,
    }
