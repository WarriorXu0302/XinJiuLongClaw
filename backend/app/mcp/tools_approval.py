"""
MCP 审批类工具 — 仅 boss/admin 可操作。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.auth import require_mcp_role
from app.mcp.deps import get_mcp_db
from app.services.audit_service import log_audit

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# 17. 确认收款
# ═══════════════════════════════════════════════════════════════════

class ConfirmPaymentRequest(BaseModel):
    order_no: str

@router.post("/confirm-order-payment")
async def mcp_confirm_order_payment(body: ConfirmPaymentRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 确认订单收款（delivered + fully_paid → completed）。admin/boss/finance。"""
    from app.models.order import Order
    from app.models.base import OrderStatus
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss', 'finance')

    order = (await db.execute(select(Order).where(Order.order_no == body.order_no))).scalar_one_or_none()
    if not order:
        raise HTTPException(404, f"订单 {body.order_no} 不存在")
    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(400, f"订单状态为 {order.status}，需要 delivered")
    if order.payment_status != 'fully_paid':
        raise HTTPException(400, f"付款状态为 {order.payment_status}，需要 fully_paid")

    from datetime import datetime, timezone
    order.status = OrderStatus.COMPLETED
    order.completed_at = datetime.now(timezone.utc)
    await db.flush()
    await log_audit(db, action="confirm_payment", entity_type="Order", entity_id=order.id, user=user)
    return {"order_no": order.order_no, "status": "completed"}


# ═══════════════════════════════════════════════════════════════════
# 18. 审批请假
# ═══════════════════════════════════════════════════════════════════

class MCPApproveLeaveRequest(BaseModel):
    request_no: str
    approved: bool = True
    reject_reason: Optional[str] = None


@router.post("/approve-leave")
async def mcp_approve_leave(body: MCPApproveLeaveRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 审批请假。admin/boss/finance。"""
    from app.models.attendance import LeaveRequest
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss', 'finance')

    req = (await db.execute(select(LeaveRequest).where(LeaveRequest.request_no == body.request_no))).scalar_one_or_none()
    if not req:
        raise HTTPException(404, "请假单不存在")
    if req.status != 'pending':
        raise HTTPException(400, f"状态为 {req.status}，不能审批")

    req.status = 'approved' if body.approved else 'rejected'
    req.reject_reason = body.reject_reason if not body.approved else None
    await db.flush()
    return {"request_no": req.request_no, "status": req.status}


# ═══════════════════════════════════════════════════════════════════
# 19. 审批工资
# ═══════════════════════════════════════════════════════════════════

class MCPApproveSalaryRequest(BaseModel):
    salary_record_id: str
    approved: bool = True
    reject_reason: Optional[str] = None


@router.post("/approve-salary")
async def mcp_approve_salary(body: MCPApproveSalaryRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 审批工资。admin/boss/finance。"""
    from app.models.payroll import SalaryRecord
    from datetime import datetime, timezone
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss', 'finance')

    rec = await db.get(SalaryRecord, body.salary_record_id)
    if not rec:
        raise HTTPException(404, "工资单不存在")
    if rec.status != 'pending_approval':
        raise HTTPException(400, f"状态为 {rec.status}，不能审批")

    now = datetime.now(timezone.utc)
    if body.approved:
        rec.status = 'approved'
        rec.approved_at = now
        rec.approved_by = user.get("employee_id")
    else:
        rec.status = 'rejected'
        rec.reject_reason = body.reject_reason or '已驳回'
    await db.flush()
    await log_audit(db, action=f"{'approve' if body.approved else 'reject'}_salary",
                    entity_type="SalaryRecord", entity_id=rec.id, user=user)
    return {"salary_record_id": rec.id, "status": rec.status}


# ═══════════════════════════════════════════════════════════════════
# 20. 审批销售目标
# ═══════════════════════════════════════════════════════════════════

class MCPApproveTargetRequest(BaseModel):
    target_id: str
    approved: bool = True
    reject_reason: Optional[str] = None


@router.post("/approve-sales-target")
async def mcp_approve_target(body: MCPApproveTargetRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 审批销售目标。admin/boss/sales_manager。"""
    from app.models.sales_target import SalesTarget
    from datetime import datetime, timezone
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss', 'sales_manager')

    t = await db.get(SalesTarget, body.target_id)
    if not t:
        raise HTTPException(404, "目标不存在")
    if t.status != 'pending_approval':
        raise HTTPException(400, f"状态为 {t.status}，不能审批")

    now = datetime.now(timezone.utc)
    if body.approved:
        t.status = 'approved'
        t.approved_at = now
        t.approved_by = user.get("employee_id")
    else:
        t.status = 'rejected'
        t.reject_reason = body.reject_reason or '已驳回'
    await db.flush()
    return {"target_id": t.id, "status": t.status}


# ═══════════════════════════════════════════════════════════════════
# 21. 审批资金调拨
# ═══════════════════════════════════════════════════════════════════

class ApproveTransferRequest(BaseModel):
    transfer_id: str

@router.post("/approve-fund-transfer")
async def mcp_approve_transfer(body: ApproveTransferRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 批准资金调拨（直接执行）。admin/boss/finance。"""
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss', 'finance')
    from app.api.routes.accounts import approve_fund_transfer
    return await approve_fund_transfer(transfer_id=body.transfer_id, user=user, db=db)
