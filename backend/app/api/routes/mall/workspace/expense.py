"""
/api/mall/workspace/expense-claims

业务员报销：列表（我申请的）+ 创建。
applicant_id = linked_employee_id；status='pending' 等 ERP 财务审批。
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
from app.models.expense_claim import ExpenseClaim
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
    return f"EC{datetime.now(timezone.utc).strftime('%Y%m%d')}{uuid.uuid4().hex[:6].upper()}"


@router.get("")
async def list_claims(
    current: CurrentMallUser,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_linked(current, db)
    stmt = select(ExpenseClaim).where(ExpenseClaim.applicant_id == user.linked_employee_id)
    if status:
        stmt = stmt.where(ExpenseClaim.status == status)
    stmt = stmt.order_by(desc(ExpenseClaim.created_at)).limit(100)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "records": [
            {
                "id": r.id,
                "claim_no": r.claim_no,
                "claim_type": r.claim_type,
                "brand_id": r.brand_id,
                "title": r.title,
                "description": r.description,
                "amount": float(r.amount) if r.amount else 0,
                "voucher_urls": r.voucher_urls or [],
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    }


class _CreateBody(BaseModel):
    claim_type: str = "daily"  # f_class / daily
    brand_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    amount: Decimal
    voucher_urls: Optional[list] = None


@router.post("")
async def create_claim(
    body: _CreateBody,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_linked(current, db)
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于 0")
    rec = ExpenseClaim(
        id=str(uuid.uuid4()),
        claim_no=_gen_no(),
        claim_type=body.claim_type,
        brand_id=body.brand_id,
        title=body.title,
        description=body.description,
        amount=body.amount,
        voucher_urls=body.voucher_urls,
        status="pending",
        applicant_id=user.linked_employee_id,
    )
    db.add(rec)
    await db.flush()
    return {
        "id": rec.id,
        "claim_no": rec.claim_no,
        "status": rec.status,
    }
