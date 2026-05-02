"""
/api/mall/workspace/expense-claims

业务员报销：列表（我申请的）+ 创建。
applicant_id = linked_employee_id；status='pending' 等 ERP 财务审批。
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
from app.models.expense_claim import ExpenseClaim
from app.services.mall import auth_service

router = APIRouter()


async def _require_linked(current, db):
    user = await auth_service.verify_token_and_load_user(db, current)
    if user.user_type != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可访问")
    if not user.linked_employee_id:
        raise HTTPException(status_code=400, detail="业务员未绑定员工记录")
    # 校验 employee 在职（避免离职员工提报销）
    from app.models.user import Employee
    emp = await db.get(Employee, user.linked_employee_id)
    if emp is None:
        raise HTTPException(status_code=400, detail="绑定的员工记录不存在")
    emp_status = getattr(emp, "status", None)
    if emp_status and emp_status != "active":
        raise HTTPException(
            status_code=403,
            detail=f"员工状态 {emp_status}，无法提交报销",
        )
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
    request: Request,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_linked(current, db)
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于 0")
    if body.claim_type not in ("daily", "f_class"):
        raise HTTPException(status_code=400, detail="claim_type 必须是 daily 或 f_class")
    # f_class 走政策兑付，必须选品牌；daily 可以不选
    if body.claim_type == "f_class" and not body.brand_id:
        raise HTTPException(status_code=400, detail="F 类报销必须选择对应品牌")
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

    # 审计：钱的事，提交/审批/支付三个关键节点都要留痕
    from app.services.audit_service import log_audit
    await log_audit(
        db, action="mall_expense_claim.submit",
        entity_type="ExpenseClaim", entity_id=rec.id,
        mall_user_id=user.id, actor_type="mall_user",
        request=request,
        changes={
            "claim_no": rec.claim_no,
            "claim_type": body.claim_type,
            "brand_id": body.brand_id,
            "amount": str(body.amount),
            "title": body.title,
        },
    )

    await db.flush()
    return {
        "id": rec.id,
        "claim_no": rec.claim_no,
        "status": rec.status,
    }
