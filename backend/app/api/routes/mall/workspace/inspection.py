"""
/api/mall/workspace/inspection-cases

业务员扫码稽查 — 列表 + 创建案件。
创建后 status='pending'，进 ERP 财务审批；小程序只做填报入口。
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
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
    from app.models.user import Employee
    emp = await db.get(Employee, user.linked_employee_id)
    if emp is None:
        raise HTTPException(status_code=400, detail="绑定的员工记录不存在")
    emp_status = getattr(emp, "status", None)
    if emp_status and emp_status != "active":
        raise HTTPException(status_code=403, detail=f"员工状态 {emp_status}，无法提交稽查")
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
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_linked(current, db)
    # 必须有 barcode 或 qrcode 其一，否则稽查缺凭据
    if not body.barcode and not body.qrcode:
        raise HTTPException(status_code=400, detail="请至少提供 barcode 或 qrcode 其一")
    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="数量必须大于 0")
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

    # 审计：稽查案件涉及扣款，mall 侧提交渠道必留痕（A1 亏损 = 回收价 - 到手价 × 瓶数）
    from app.services.audit_service import log_audit
    await log_audit(
        db, action="mall_inspection_case.submit",
        entity_type="InspectionCase", entity_id=rec.id,
        mall_user_id=user.id, actor_type="mall_user",
        request=request,
        changes={
            "case_no": rec.case_no,
            "case_type": body.case_type,
            "barcode": body.barcode,
            "qrcode": body.qrcode,
            "brand_id": body.brand_id,
            "product_id": body.product_id,
            "quantity": body.quantity,
            "original_sale_price": str(body.original_sale_price) if body.original_sale_price else None,
        },
    )

    await db.flush()
    return {
        "id": rec.id,
        "case_no": rec.case_no,
        "status": rec.status,
    }
