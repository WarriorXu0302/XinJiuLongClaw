"""
/api/mall/workspace/leave-requests

业务员在小程序里看/提交自己的请假申请。薄转发到 ERP 现有 leave_requests 数据（同一张表）。
ERP HR 后台审批 pending 记录。
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.attendance import LeaveRequest
from app.services.mall import auth_service

router = APIRouter()


async def _require_linked_salesman(current, db):
    user = await auth_service.verify_token_and_load_user(db, current)
    if user.user_type != "salesman":
        raise HTTPException(status_code=403, detail="仅业务员可访问")
    if not user.linked_employee_id:
        raise HTTPException(status_code=400, detail="业务员未绑定员工记录")
    return user


def _calc_days(start: date, end: date, half_start: bool = False, half_end: bool = False) -> Decimal:
    n = (end - start).days + 1
    days = Decimal(str(n))
    if half_start:
        days -= Decimal("0.5")
    if half_end:
        days -= Decimal("0.5")
    return max(days, Decimal("0.5"))


def _gen_no() -> str:
    return f"LV{datetime.now(timezone.utc).strftime('%Y%m%d')}{uuid.uuid4().hex[:6].upper()}"


@router.get("")
async def list_my_leaves(
    current: CurrentMallUser,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_linked_salesman(current, db)
    stmt = select(LeaveRequest).where(LeaveRequest.employee_id == user.linked_employee_id)
    if status:
        stmt = stmt.where(LeaveRequest.status == status)
    stmt = stmt.order_by(desc(LeaveRequest.created_at)).limit(100)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "records": [
            {
                "id": r.id,
                "request_no": r.request_no,
                "leave_type": r.leave_type,
                "start_date": r.start_date,
                "end_date": r.end_date,
                "total_days": float(r.total_days) if r.total_days else 0,
                "reason": r.reason,
                "status": r.status,
                "created_at": r.created_at,
                "reject_reason": r.reject_reason,
            }
            for r in rows
        ]
    }


class _CreateBody(BaseModel):
    leave_type: str  # annual / sick / personal / overtime_off
    start_date: date
    end_date: date
    half_day_start: bool = False
    half_day_end: bool = False
    reason: Optional[str] = None


@router.post("")
async def create_leave(
    body: _CreateBody,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await _require_linked_salesman(current, db)
    if body.end_date < body.start_date:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
    total = _calc_days(body.start_date, body.end_date, body.half_day_start, body.half_day_end)
    rec = LeaveRequest(
        id=str(uuid.uuid4()),
        request_no=_gen_no(),
        employee_id=user.linked_employee_id,
        leave_type=body.leave_type,
        start_date=body.start_date,
        end_date=body.end_date,
        half_day_start=body.half_day_start,
        half_day_end=body.half_day_end,
        total_days=total,
        reason=body.reason,
        status="pending",
    )
    db.add(rec)
    await db.flush()
    return {
        "id": rec.id,
        "request_no": rec.request_no,
        "status": rec.status,
        "total_days": float(rec.total_days),
    }
