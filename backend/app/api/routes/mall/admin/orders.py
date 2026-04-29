"""
/api/mall/admin/orders/*

ERP 管理员端点（用 ERP CurrentUser + require_role）：
  POST /{id}/reassign         强制改派
  POST /{id}/confirm-payment  财务确认收款 → 触发 commission

列表/详情走 ERP 管理台（React），M5 再补。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.services.mall import order_service

router = APIRouter()


class _ReassignBody(BaseModel):
    target_salesman_user_id: str
    reason: Optional[str] = None


@router.post("/{order_id}/reassign")
async def reassign(
    order_id: str,
    body: _ReassignBody,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss")
    # admin 端走 ERP get_db（admin session，不过 RLS），但我们操作 mall_* 表；
    # mall_* 表没 RLS 策略，read/write 正常
    order = await order_service.admin_reassign(
        db, order_id,
        target_salesman_id=body.target_salesman_user_id,
        operator_erp_user_id=user["sub"],
        reason=body.reason,
    )
    return {"order_no": order.order_no, "status": order.status,
            "assigned_salesman_id": order.assigned_salesman_id}


@router.post("/{order_id}/confirm-payment")
async def confirm_payment(
    order_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "admin", "boss", "finance")
    employee_id = user.get("employee_id")
    if not employee_id:
        raise HTTPException(status_code=400, detail="操作员没有关联 employee 记录")
    order = await order_service.confirm_payment(
        db, order_id, operator_employee_id=employee_id
    )
    return {
        "order_no": order.order_no,
        "status": order.status,
        "payment_status": order.payment_status,
        "received_amount": str(order.received_amount),
        "pay_amount": str(order.pay_amount),
        "commission_posted": order.commission_posted,
    }
