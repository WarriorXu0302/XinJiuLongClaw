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
    """AI 审批请假。admin/boss/hr。"""
    from app.models.attendance import LeaveRequest
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss', 'hr')

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
    """AI 批准资金调拨（直接执行）。admin/boss。"""
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss')
    from app.api.routes.accounts import approve_fund_transfer
    return await approve_fund_transfer(transfer_id=body.transfer_id, user=user, db=db)


# ═══════════════════════════════════════════════════════════════════
# 22. 审批采购单
# ═══════════════════════════════════════════════════════════════════

class MCPApprovePurchaseOrderRequest(BaseModel):
    po_id: str
    action: str = "approve"  # approve / reject
    reject_reason: Optional[str] = None


@router.post("/approve-purchase-order")
async def mcp_approve_purchase_order(body: MCPApprovePurchaseOrderRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 审批采购单。approve → approved；reject → cancelled。"""
    from app.models.purchase import PurchaseOrder
    from datetime import datetime, timezone
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss', 'finance')

    po = await db.get(PurchaseOrder, body.po_id)
    if not po:
        raise HTTPException(404, f"采购单 {body.po_id} 不存在")
    if po.status != "pending":
        raise HTTPException(400, f"采购单状态为 {po.status}，只有 pending 可审批")

    if body.action == "approve":
        po.status = "approved"
        po.approved_by = user.get("employee_id")
    elif body.action == "reject":
        po.status = "cancelled"
        po.notes = (po.notes or "") + f"\n驳回原因: {body.reject_reason or '已驳回'}"
    else:
        raise HTTPException(400, f"不支持的 action: {body.action}，可选: approve / reject")
    await db.flush()
    await log_audit(db, action=f"{body.action}_purchase_order", entity_type="PurchaseOrder", entity_id=po.id, user=user)
    return {"po_id": po.id, "po_no": po.po_no, "status": po.status}


# ═══════════════════════════════════════════════════════════════════
# 23. 审批费用
# ═══════════════════════════════════════════════════════════════════

class MCPApproveExpenseRequest(BaseModel):
    expense_id: str
    action: str = "approve"  # approve / reject / pay
    reject_reason: Optional[str] = None


@router.post("/approve-expense")
async def mcp_approve_expense(body: MCPApproveExpenseRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 审批费用。approve → approved；reject → rejected（驳回）；pay → paid（标记已付）。"""
    from app.models.expense_claim import ExpenseClaim
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss', 'finance')

    claim = await db.get(ExpenseClaim, body.expense_id)
    if not claim:
        raise HTTPException(404, f"费用 {body.expense_id} 不存在")

    if body.action == "approve":
        if claim.status != "pending":
            raise HTTPException(400, f"费用状态为 {claim.status}，只有 pending 可审批通过")
        claim.status = "approved"
        claim.approved_by = user.get("employee_id")
    elif body.action == "reject":
        if claim.status != "pending":
            raise HTTPException(400, f"费用状态为 {claim.status}，只有 pending 可驳回")
        claim.status = "rejected"
        claim.notes = (claim.notes or "") + f"\n驳回原因: {body.reject_reason or '已驳回'}"
    elif body.action == "pay":
        if claim.status != "approved":
            raise HTTPException(400, f"费用状态为 {claim.status}，只有 approved 可标记已付")
        claim.status = "paid"
    else:
        raise HTTPException(400, f"不支持的 action: {body.action}，可选: approve / reject / pay")
    await db.flush()
    await log_audit(db, action=f"{body.action}_expense", entity_type="ExpenseClaim", entity_id=claim.id, user=user)
    return {"expense_id": claim.id, "claim_no": claim.claim_no, "status": claim.status}


# ═══════════════════════════════════════════════════════════════════
# 24. 执行稽查案件
# ═══════════════════════════════════════════════════════════════════

class MCPApproveInspectionRequest(BaseModel):
    case_id: str
    action: str = "execute"  # execute


@router.post("/approve-inspection")
async def mcp_approve_inspection(body: MCPApproveInspectionRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 执行稽查案件（pending → confirmed）。只有已执行案件才进利润台账。"""
    from app.models.inspection import InspectionCase
    from datetime import datetime, timezone
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss', 'finance')

    case = await db.get(InspectionCase, body.case_id)
    if not case:
        raise HTTPException(404, f"稽查案件 {body.case_id} 不存在")

    if body.action != "execute":
        raise HTTPException(400, f"不支持的 action: {body.action}，可选: execute")
    if case.status != "pending":
        raise HTTPException(400, f"案件状态为 {case.status}，只有 pending 可执行")

    case.status = "confirmed"
    case.closed_at = datetime.now(timezone.utc)
    await db.flush()
    await log_audit(db, action="execute_inspection", entity_type="InspectionCase", entity_id=case.id, user=user)
    return {
        "case_id": case.id, "case_no": case.case_no,
        "status": case.status, "profit_loss": float(case.profit_loss),
    }


# ═══════════════════════════════════════════════════════════════════
# 25. 拒绝资金调拨
# ═══════════════════════════════════════════════════════════════════

class RejectTransferRequest(BaseModel):
    transfer_id: str
    reject_reason: Optional[str] = None


@router.post("/reject-fund-transfer")
async def mcp_reject_fund_transfer(body: RejectTransferRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 拒绝资金调拨申请。将 transfer_pending → transfer_rejected。"""
    from app.models.fund_flow import FundFlow
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss')

    ff = await db.get(FundFlow, body.transfer_id)
    if ff is None:
        raise HTTPException(404, "拨款申请不存在")
    if ff.flow_type != 'transfer_pending':
        raise HTTPException(400, "该记录不是待审批的拨款申请")

    ff.flow_type = 'transfer_rejected'
    reason = body.reject_reason or '已驳回'
    ff.notes = (ff.notes or '').replace('待审批：', f'已驳回（{reason}）：') if '待审批：' in (ff.notes or '') else f"已驳回：{reason}"
    await db.flush()
    await log_audit(db, action="reject_fund_transfer", entity_type="FundFlow", entity_id=ff.id, user=user)
    return {"transfer_id": ff.id, "status": "rejected"}


# ═══════════════════════════════════════════════════════════════════
# 26. 审批融资还款
# ═══════════════════════════════════════════════════════════════════

class MCPApproveFinancingRepaymentRequest(BaseModel):
    repayment_id: str
    action: str = "approve"  # approve / reject
    reject_reason: Optional[str] = None


@router.post("/approve-financing-repayment")
async def mcp_approve_financing_repayment(body: MCPApproveFinancingRepaymentRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 审批融资还款。approve 调用内部逻辑执行扣款；reject 直接驳回。"""
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss')

    if body.action == "approve":
        from app.api.routes.financing import approve_repayment
        return await approve_repayment(repayment_id=body.repayment_id, user=user, db=db)
    elif body.action == "reject":
        from app.models.financing import FinancingRepayment
        rep = await db.get(FinancingRepayment, body.repayment_id)
        if not rep:
            raise HTTPException(404, "还款申请不存在")
        if rep.status != "pending":
            raise HTTPException(400, f"状态为 '{rep.status}'，不是待审批")
        rep.status = "rejected"
        rep.reject_reason = body.reject_reason or "已驳回"
        rep.approved_by = user.get("employee_id")
        # Cancel linked PO if exists
        if rep.purchase_order_id:
            from app.models.purchase import PurchaseOrder
            po = await db.get(PurchaseOrder, rep.purchase_order_id)
            if po:
                po.status = "cancelled"
        await db.flush()
        await log_audit(db, action="reject_financing_repayment", entity_type="FinancingRepayment", entity_id=rep.id, user=user)
        return {"repayment_id": rep.id, "status": "rejected"}
    else:
        raise HTTPException(400, f"不支持的 action: {body.action}，可选: approve / reject")


# ═══════════════════════════════════════════════════════════════════
# 27. 审批报销理赔
# ═══════════════════════════════════════════════════════════════════

class MCPApproveExpenseClaimRequest(BaseModel):
    claim_id: str
    action: str = "approve"  # approve / reject / pay
    reject_reason: Optional[str] = None


@router.post("/approve-expense-claim")
async def mcp_approve_expense_claim(body: MCPApproveExpenseClaimRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 审批报销理赔。approve（通过）/ reject（驳回）/ pay（标记已付）。"""
    from app.models.expense_claim import ExpenseClaim
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss', 'finance')

    claim = await db.get(ExpenseClaim, body.claim_id)
    if not claim:
        raise HTTPException(404, f"报销理赔 {body.claim_id} 不存在")

    if body.action == "approve":
        if claim.status != "pending":
            raise HTTPException(400, f"状态为 {claim.status}，只有 pending 可审批通过")
        claim.status = "approved"
        claim.approved_by = user.get("employee_id")
    elif body.action == "reject":
        if claim.status != "pending":
            raise HTTPException(400, f"状态为 {claim.status}，只有 pending 可驳回")
        claim.status = "rejected"
        claim.notes = (claim.notes or "") + f"\n驳回原因: {body.reject_reason or '已驳回'}"
    elif body.action == "pay":
        if claim.status != "approved":
            raise HTTPException(400, f"状态为 {claim.status}，只有 approved 可标记已付")
        claim.status = "paid"
    else:
        raise HTTPException(400, f"不支持的 action: {body.action}，可选: approve / reject / pay")

    await db.flush()
    await log_audit(db, action=f"{body.action}_expense_claim", entity_type="ExpenseClaim", entity_id=claim.id, user=user)
    return {"claim_id": claim.id, "claim_no": claim.claim_no, "status": claim.status}
