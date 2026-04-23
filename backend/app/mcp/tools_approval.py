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
# 28. 订单审批（pending → approved，一步完成提交+审批）
# ═══════════════════════════════════════════════════════════════════

class MCPApproveOrderRequest(BaseModel):
    order_no: str
    action: str = "approve"  # approve / reject
    reject_reason: Optional[str] = None
    need_external: bool = False


@router.post("/approve-order")
async def mcp_approve_order(body: MCPApproveOrderRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 审批订单。pending 自动先提交再审批；policy_pending_internal 直接审批。"""
    from app.models.order import Order
    from app.models.base import OrderStatus
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss')

    order = (await db.execute(select(Order).where(Order.order_no == body.order_no))).scalar_one_or_none()
    if not order:
        raise HTTPException(404, f"订单 {body.order_no} 不存在")

    if body.action == "reject":
        if order.status not in (OrderStatus.PENDING, OrderStatus.POLICY_PENDING_INTERNAL, OrderStatus.POLICY_PENDING_EXTERNAL):
            raise HTTPException(400, f"订单状态为 {order.status}，无法驳回")
        order.status = OrderStatus.REJECTED
        order.rejection_reason = body.reject_reason or "已驳回"
        await db.flush()
        await log_audit(db, action="reject_order", entity_type="Order", entity_id=order.id, user=user)
        await db.refresh(order, ["customer"])
        return {"order_no": order.order_no, "status": order.status,
                "customer": order.customer.name if order.customer else None,
                "total_amount": float(order.total_amount) if order.total_amount else 0,
                "settlement_mode": order.settlement_mode}

    # approve flow
    if order.status == OrderStatus.PENDING:
        order.status = OrderStatus.POLICY_PENDING_INTERNAL
        await db.flush()
    if order.status == OrderStatus.POLICY_PENDING_INTERNAL:
        order.status = OrderStatus.POLICY_PENDING_EXTERNAL if body.need_external else OrderStatus.APPROVED
        await db.flush()
    elif order.status == OrderStatus.POLICY_PENDING_EXTERNAL:
        order.status = OrderStatus.APPROVED
        await db.flush()
    else:
        raise HTTPException(400, f"订单状态为 {order.status}，无法审批（需要 pending/policy_pending_internal/policy_pending_external）")

    await log_audit(db, action="approve_order", entity_type="Order", entity_id=order.id, user=user)
    await db.refresh(order, ["customer"])
    return {"order_no": order.order_no, "status": order.status,
            "customer": order.customer.name if order.customer else None,
            "total_amount": float(order.total_amount) if order.total_amount else 0,
            "settlement_mode": order.settlement_mode}


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
    await db.refresh(order, ["customer"])
    return {"order_no": order.order_no, "status": "completed",
            "customer": order.customer.name if order.customer else None,
            "total_amount": float(order.total_amount) if order.total_amount else 0}


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
    await db.refresh(req, ["employee"])
    return {"request_no": req.request_no, "status": req.status,
            "employee": req.employee.name if req.employee else None,
            "leave_type": req.leave_type,
            "start_date": str(req.start_date), "end_date": str(req.end_date),
            "total_days": float(req.total_days) if req.total_days else 0}


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
    await db.refresh(rec, ["employee"])
    return {"salary_record_id": rec.id, "status": rec.status,
            "employee": rec.employee.name if rec.employee else None,
            "period": rec.period,
            "actual_pay": float(rec.actual_pay) if rec.actual_pay else 0}


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
        po = (await db.execute(select(PurchaseOrder).where(PurchaseOrder.po_no == body.po_id))).scalar_one_or_none()
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
    await db.refresh(po, ["supplier"])
    return {"po_id": po.id, "po_no": po.po_no, "status": po.status,
            "supplier": po.supplier.name if po.supplier else None,
            "total_amount": float(po.total_amount) if po.total_amount else 0}


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
        claim = (await db.execute(select(ExpenseClaim).where(ExpenseClaim.claim_no == body.expense_id))).scalar_one_or_none()
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
        # ── 扣款逻辑（与 finance.py pay_expense 一致）──
        from decimal import Decimal
        from app.models.product import Account
        from app.api.routes.accounts import record_fund_flow
        # 找付款账户：优先用 claim 上已指定的，否则找品牌现金账户
        account = None
        if claim.paid_account_id:
            account = await db.get(Account, claim.paid_account_id)
        if not account and claim.brand_id:
            account = (await db.execute(
                select(Account).where(
                    Account.brand_id == claim.brand_id,
                    Account.account_type == 'cash',
                    Account.level == 'project',
                )
            )).scalar_one_or_none()
        if account:
            amt = Decimal(str(claim.amount))
            if account.balance < amt:
                raise HTTPException(400, f"账户余额不足（{account.name} 余额 ¥{account.balance}，需付 ¥{amt}）")
            account.balance -= amt
            claim.paid_account_id = account.id
            await record_fund_flow(
                db, account_id=account.id, flow_type='debit',
                amount=amt, balance_after=account.balance,
                related_type='expense_claim', related_id=claim.id,
                notes=f"报销付款 {claim.claim_no}",
                created_by=user.get("employee_id"),
                brand_id=claim.brand_id,
            )
        claim.status = "paid"
    else:
        raise HTTPException(400, f"不支持的 action: {body.action}，可选: approve / reject / pay")
    await db.flush()
    await log_audit(db, action=f"{body.action}_expense", entity_type="ExpenseClaim", entity_id=claim.id, user=user)
    await db.refresh(claim, ["brand"])
    return {"expense_id": claim.id, "claim_no": claim.claim_no, "status": claim.status,
            "amount": float(claim.amount) if claim.amount else 0,
            "title": claim.title,
            "brand": claim.brand.name if claim.brand else None}


# ═══════════════════════════════════════════════════════════════════
# 24. 执行稽查案件
# ═══════════════════════════════════════════════════════════════════

class MCPApproveInspectionRequest(BaseModel):
    case_id: str
    action: str = "execute"  # execute


@router.post("/approve-inspection")
async def mcp_approve_inspection(body: MCPApproveInspectionRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 执行稽查案件。pending → approved → executed（完整执行含扣款+库存）。

    执行阶段完成（与 inspections.py execute_inspection_case 一致）：
      A1/A2: 扣品牌现金(回收款+罚款) + 入库
      A3: 扣品牌现金(罚款)
      B1: 备用库出库 + 品牌现金收款
      B2: 入主仓 + 扣品牌现金(买入款)
    """
    from app.models.inspection import InspectionCase
    from datetime import datetime, timezone
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss', 'finance')

    case = await db.get(InspectionCase, body.case_id)
    if not case:
        case = (await db.execute(select(InspectionCase).where(InspectionCase.case_no == body.case_id))).scalar_one_or_none()
    if not case:
        raise HTTPException(404, f"稽查案件 {body.case_id} 不存在")

    if body.action != "execute":
        raise HTTPException(400, f"不支持的 action: {body.action}，可选: execute")

    now = datetime.now(timezone.utc)

    if case.status == "pending":
        # 第一步：审批通过 pending → approved
        case.status = "approved"
        await db.flush()
        await log_audit(db, action="approve_inspection", entity_type="InspectionCase", entity_id=case.id, user=user)
        # fall through 到执行阶段

    if case.status == "approved":
        # 第二步：执行完整的账务处理（与 inspections.py execute_inspection_case 一致）
        from decimal import Decimal
        from app.models.product import Account, Product, Warehouse
        from app.models.inventory import Inventory, StockFlow
        from app.api.routes.accounts import record_fund_flow
        import uuid as _uuid

        if not case.brand_id or not case.product_id:
            # 缺少必要信息，仅更新状态 + 警告
            case.status = "executed"
            case.closed_at = now
            await db.flush()
            await log_audit(db, action="execute_inspection", entity_type="InspectionCase", entity_id=case.id, user=user)
            return {
                "case_id": case.id, "case_no": case.case_no,
                "status": case.status, "profit_loss": float(case.profit_loss or 0),
                "warning": "案件缺少品牌或商品信息，仅更新状态，未执行账务处理",
            }

        # 瓶数换算
        prod = await db.get(Product, case.product_id)
        bpc = prod.bottles_per_case if prod and prod.bottles_per_case else 1
        bottles = case.quantity * bpc if case.quantity_unit == '箱' else case.quantity
        if bottles <= 0:
            raise HTTPException(400, "案件数量为 0，无法执行")

        # 品牌现金账户
        brand_cash_acc = (await db.execute(
            select(Account).where(
                Account.brand_id == case.brand_id,
                Account.account_type == 'cash',
                Account.level == 'project',
            )
        )).scalar_one_or_none()
        if not brand_cash_acc:
            raise HTTPException(400, "该品牌未配置现金账户，无法执行稽查扣款")

        # 预算总支出，校验余额
        total_debit = Decimal("0")
        if case.case_type in ('outflow_malicious', 'outflow_nonmalicious'):
            total_debit += (case.purchase_price or Decimal("0")) * bottles
        if case.case_type in ('outflow_malicious', 'outflow_nonmalicious', 'outflow_transfer'):
            total_debit += case.penalty_amount or Decimal("0")
        if case.case_type == 'inflow_transfer':
            total_debit += (case.purchase_price or Decimal("0")) * bottles
        if total_debit > 0 and brand_cash_acc.balance < total_debit:
            raise HTTPException(400,
                f"品牌现金账户余额不足：¥{brand_cash_acc.balance} < 需付 ¥{total_debit}。请先调拨到品牌现金账户。")

        # 1. 付款/收款
        if case.case_type in ('outflow_malicious', 'outflow_nonmalicious'):
            pay_amt = (case.purchase_price or Decimal("0")) * bottles
            if pay_amt > 0:
                brand_cash_acc.balance -= pay_amt
                await record_fund_flow(db, account_id=brand_cash_acc.id, flow_type='debit', amount=pay_amt,
                    balance_after=brand_cash_acc.balance, related_type='inspection_payment', related_id=case.id,
                    notes=f"稽查回收付款 {case.case_no} ({bottles}瓶)")
        if case.case_type in ('outflow_malicious', 'outflow_nonmalicious', 'outflow_transfer') and (case.penalty_amount or 0) > 0:
            brand_cash_acc.balance -= case.penalty_amount
            await record_fund_flow(db, account_id=brand_cash_acc.id, flow_type='debit', amount=case.penalty_amount,
                balance_after=brand_cash_acc.balance, related_type='inspection_penalty', related_id=case.id,
                notes=f"稽查罚款 {case.case_no}")
        if case.case_type == 'inflow_transfer':
            pay_amt = (case.purchase_price or Decimal("0")) * bottles
            if pay_amt > 0:
                brand_cash_acc.balance -= pay_amt
                await record_fund_flow(db, account_id=brand_cash_acc.id, flow_type='debit', amount=pay_amt,
                    balance_after=brand_cash_acc.balance, related_type='inspection_payment', related_id=case.id,
                    notes=f"转码入库付款 {case.case_no} ({bottles}瓶)")
        if case.case_type == 'inflow_resell':
            income = (case.resell_price or Decimal("0")) * bottles
            if income > 0:
                brand_cash_acc.balance += income
                await record_fund_flow(db, account_id=brand_cash_acc.id, flow_type='credit', amount=income,
                    balance_after=brand_cash_acc.balance, related_type='inspection_income', related_id=case.id,
                    notes=f"清理回售收款 {case.case_no} ({bottles}瓶)")

        # 2. 入库/出库
        main_wh = (await db.execute(
            select(Warehouse).where(Warehouse.brand_id == case.brand_id, Warehouse.warehouse_type == 'main', Warehouse.is_active == True)
        )).scalar_one_or_none()
        backup_wh = (await db.execute(
            select(Warehouse).where(Warehouse.brand_id == case.brand_id, Warehouse.warehouse_type == 'backup', Warehouse.is_active == True)
        )).scalar_one_or_none()

        def _gen_flow_no():
            _ts = now.strftime("%Y%m%d%H%M%S")
            return f"SF-{_ts}-{_uuid.uuid4().hex[:6]}"

        batch_no = f"IC-{case.case_no}"
        target_wh = None
        cost_price = None
        if case.case_type == 'outflow_malicious':
            target_wh = backup_wh
            cost_price = case.purchase_price
        elif case.case_type == 'outflow_nonmalicious':
            target_wh = main_wh
            cost_price = case.original_sale_price or case.purchase_price
        elif case.case_type == 'inflow_transfer':
            target_wh = main_wh
            cost_price = case.original_sale_price or case.purchase_price

        if target_wh and cost_price is not None:
            existing_inv = (await db.execute(
                select(Inventory).where(
                    Inventory.product_id == case.product_id,
                    Inventory.warehouse_id == target_wh.id,
                    Inventory.batch_no == batch_no,
                )
            )).scalar_one_or_none()
            if existing_inv:
                existing_inv.quantity += bottles
            else:
                db.add(Inventory(
                    product_id=case.product_id, warehouse_id=target_wh.id,
                    batch_no=batch_no, quantity=bottles, cost_price=cost_price,
                    stock_in_date=now,
                ))
            db.add(StockFlow(
                id=str(_uuid.uuid4()), flow_no=_gen_flow_no(),
                flow_type="inbound", product_id=case.product_id, warehouse_id=target_wh.id,
                batch_no=batch_no, cost_price=cost_price, quantity=bottles,
                reference_no=case.case_no, notes=f"稽查入库 {case.case_no} ({bottles}瓶)",
            ))
        elif case.case_type == 'inflow_resell' and backup_wh:
            # B1 从备用库出库
            inv_rows = (await db.execute(
                select(Inventory).where(
                    Inventory.product_id == case.product_id,
                    Inventory.warehouse_id == backup_wh.id,
                    Inventory.quantity > 0,
                ).order_by(Inventory.stock_in_date.asc())
            )).scalars().all()
            available = sum(r.quantity for r in inv_rows)
            if available < bottles:
                raise HTTPException(400, f"备用库库存不足：需要{bottles}瓶，可用{available}瓶")
            remaining = bottles
            for inv in inv_rows:
                if remaining <= 0:
                    break
                deduct = min(inv.quantity, remaining)
                inv.quantity -= deduct
                remaining -= deduct
            db.add(StockFlow(
                id=str(_uuid.uuid4()), flow_no=_gen_flow_no(),
                flow_type="outbound", product_id=case.product_id, warehouse_id=backup_wh.id,
                batch_no=inv_rows[0].batch_no if inv_rows else "fallback", quantity=bottles,
                reference_no=case.case_no, notes=f"稽查回售出库 {case.case_no} ({bottles}瓶)",
            ))

        # 3. 更新状态
        case.status = 'executed'
        case.closed_at = now
        await db.flush()
        await log_audit(db, action="execute_inspection", entity_type="InspectionCase", entity_id=case.id, user=user)
        return {
            "case_id": case.id, "case_no": case.case_no,
            "status": case.status, "profit_loss": float(case.profit_loss or 0),
            "bottles": bottles,
        }

    raise HTTPException(400, f"案件状态为 {case.status}，只有 pending 或 approved 可执行")


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
    require_mcp_role(user, 'boss', 'finance')

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
        claim = (await db.execute(select(ExpenseClaim).where(ExpenseClaim.claim_no == body.claim_id))).scalar_one_or_none()
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
        # ── 扣款逻辑（与 finance.py pay_expense 一致）──
        from decimal import Decimal
        from app.models.product import Account
        from app.api.routes.accounts import record_fund_flow
        account = None
        if claim.paid_account_id:
            account = await db.get(Account, claim.paid_account_id)
        if not account and claim.brand_id:
            account = (await db.execute(
                select(Account).where(
                    Account.brand_id == claim.brand_id,
                    Account.account_type == 'cash',
                    Account.level == 'project',
                )
            )).scalar_one_or_none()
        if account:
            amt = Decimal(str(claim.amount))
            if account.balance < amt:
                raise HTTPException(400, f"账户余额不足（{account.name} 余额 ¥{account.balance}，需付 ¥{amt}）")
            account.balance -= amt
            claim.paid_account_id = account.id
            await record_fund_flow(
                db, account_id=account.id, flow_type='debit',
                amount=amt, balance_after=account.balance,
                related_type='expense_claim', related_id=claim.id,
                notes=f"报销付款 {claim.claim_no}",
                created_by=user.get("employee_id"),
                brand_id=claim.brand_id,
            )
        claim.status = "paid"
    else:
        raise HTTPException(400, f"不支持的 action: {body.action}，可选: approve / reject / pay")

    await db.flush()
    await log_audit(db, action=f"{body.action}_expense_claim", entity_type="ExpenseClaim", entity_id=claim.id, user=user)
    return {"claim_id": claim.id, "claim_no": claim.claim_no, "status": claim.status}


# ═══════════════════════════════════════════════════════════════════
# 28. 完成订单（delivered → completed）
# ═══════════════════════════════════════════════════════════════════

class MCPCompleteOrderRequest(BaseModel):
    order_no: str


@router.post("/complete-order")
async def mcp_complete_order(body: MCPCompleteOrderRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 完成订单。将 delivered 状态的订单标记为 completed。
    与 confirm-order-payment 不同：本工具不要求 fully_paid。
    """
    from app.models.order import Order
    from app.models.base import OrderStatus
    from datetime import datetime, timezone

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss', 'finance')

    order = (await db.execute(select(Order).where(Order.order_no == body.order_no))).scalar_one_or_none()
    if not order:
        raise HTTPException(404, f"订单 {body.order_no} 不存在")
    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(400, f"订单状态为 {order.status}，需要 delivered 才能完成")

    now = datetime.now(timezone.utc)
    order.status = OrderStatus.COMPLETED
    order.completed_at = now
    await db.flush()
    await log_audit(db, action="complete_order", entity_type="Order", entity_id=order.id, user=user)
    await db.refresh(order, ["customer"])
    return {"order_no": order.order_no, "status": order.status, "completed_at": str(now),
            "customer": order.customer.name if order.customer else None,
            "total_amount": float(order.total_amount) if order.total_amount else 0}


# ═══════════════════════════════════════════════════════════════════
# 29. 审批政策理赔
# ═══════════════════════════════════════════════════════════════════

class MCPApprovePolicyClaimRequest(BaseModel):
    claim_id: str
    action: str = "approve"  # approve / reject
    reject_reason: Optional[str] = None


@router.post("/approve-policy-claim")
async def mcp_approve_policy_claim(body: MCPApprovePolicyClaimRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 审批政策理赔单。approve（通过）/ reject（驳回）。
    注意：这是 PolicyClaim（政策理赔），不同于 ExpenseClaim（费用报销）。
    """
    from app.models.policy import PolicyClaim
    from datetime import datetime, timezone

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss', 'finance')

    claim = await db.get(PolicyClaim, body.claim_id)
    if not claim:
        # 也尝试按 claim_no 查
        claim = (await db.execute(
            select(PolicyClaim).where(PolicyClaim.claim_no == body.claim_id)
        )).scalar_one_or_none()
    if not claim:
        raise HTTPException(404, f"政策理赔单 {body.claim_id} 不存在")

    if body.action == "approve":
        if claim.status != "submitted":
            raise HTTPException(400, f"状态为 {claim.status}，只有 submitted 可审批通过")
        claim.status = "approved"
    elif body.action == "reject":
        if claim.status not in ("submitted", "approved"):
            raise HTTPException(400, f"状态为 {claim.status}，不可驳回")
        claim.status = "rejected"
        claim.notes = (claim.notes or "") + f"\n驳回原因: {body.reject_reason or '已驳回'}"
    else:
        raise HTTPException(400, f"不支持的 action: {body.action}，可选: approve / reject")

    await db.flush()
    await log_audit(db, action=f"{body.action}_policy_claim", entity_type="PolicyClaim",
                    entity_id=claim.id, user=user)
    return {"claim_id": claim.id, "claim_no": claim.claim_no, "status": claim.status}


# ═══════════════════════════════════════════════════════════════════
# 30. 驳回订单政策
# ═══════════════════════════════════════════════════════════════════

class MCPRejectOrderPolicyRequest(BaseModel):
    order_no: str
    reject_reason: Optional[str] = None


@router.post("/reject-order-policy")
async def mcp_reject_order_policy(body: MCPRejectOrderPolicyRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 驳回订单政策审批。policy_pending_internal/policy_pending_external → policy_rejected。"""
    from app.models.order import Order
    from app.models.base import OrderStatus

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss')

    order = (await db.execute(select(Order).where(Order.order_no == body.order_no))).scalar_one_or_none()
    if not order:
        raise HTTPException(404, f"订单 {body.order_no} 不存在")
    if order.status not in (OrderStatus.POLICY_PENDING_INTERNAL, OrderStatus.POLICY_PENDING_EXTERNAL):
        raise HTTPException(400, f"订单状态为 {order.status}，需要 policy_pending_internal 或 policy_pending_external 才能驳回")

    order.status = OrderStatus.REJECTED
    reason = body.reject_reason or "政策审批驳回"
    order.rejection_reason = reason
    await db.flush()
    await log_audit(db, action="reject_order_policy", entity_type="Order", entity_id=order.id, user=user)
    await db.refresh(order, ["customer"])
    return {"order_no": order.order_no, "status": order.status,
            "customer": order.customer.name if order.customer else None,
            "total_amount": float(order.total_amount) if order.total_amount else 0}


# ═══════════════════════════════════════════════════════════════════
# 31. 确认厂家结算分配
# ═══════════════════════════════════════════════════════════════════

class MCPConfirmSettlementAllocationRequest(BaseModel):
    settlement_id: str
    claim_id: str
    allocated_amount: float


@router.post("/confirm-settlement-allocation")
async def mcp_confirm_settlement_allocation(body: MCPConfirmSettlementAllocationRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 确认厂家结算分配到政策理赔单。调用 policy_service.confirm_settlement_allocation。"""
    from decimal import Decimal
    from app.services.policy_service import confirm_settlement_allocation

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss', 'finance')

    link = await confirm_settlement_allocation(
        db=db,
        settlement_id=body.settlement_id,
        claim_id=body.claim_id,
        allocated_amount=Decimal(str(body.allocated_amount)),
        confirmed_by=user.get("employee_id", ""),
    )
    await db.flush()
    await log_audit(db, action="confirm_settlement_allocation", entity_type="ClaimSettlementLink", entity_id=link.id, user=user)
    return {"link_id": link.id, "settlement_id": body.settlement_id, "claim_id": body.claim_id, "allocated_amount": body.allocated_amount}


# ═══════════════════════════════════════════════════════════════════
# 32. 创建政策理赔单
# ═══════════════════════════════════════════════════════════════════

class MCPCreatePolicyClaimRequest(BaseModel):
    policy_request_id: str
    claim_type: str = "standard"
    notes: Optional[str] = None


@router.post("/create-policy-claim")
async def mcp_create_policy_claim(body: MCPCreatePolicyClaimRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建政策理赔单。自动生成 claim_no，状态 pending。"""
    from app.models.policy import PolicyRequest, PolicyClaim
    from datetime import datetime, timezone

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, 'boss', 'finance')

    pr = await db.get(PolicyRequest, body.policy_request_id)
    if not pr:
        raise HTTPException(404, f"政策申请 {body.policy_request_id} 不存在")

    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d%H%M%S")
    import uuid
    claim = PolicyClaim(
        id=str(uuid.uuid4()),
        claim_no=f"PC-{ts}-{uuid.uuid4().hex[:6]}",
        brand_id=pr.brand_id,
        claim_batch_period=now.strftime("%Y-%m"),
        notes=body.notes,
        status="draft",
        claimed_by=user.get("employee_id"),
    )
    db.add(claim)
    await db.flush()

    # 自动从政策申请的 items 创建理赔明细行，链接回 request_item
    from app.models.policy import PolicyClaimItem
    from app.models.policy_request_item import PolicyRequestItem
    request_items = (await db.execute(
        select(PolicyRequestItem).where(PolicyRequestItem.policy_request_id == pr.id)
    )).scalars().all()
    item_count = 0
    for ri in request_items:
        db.add(PolicyClaimItem(
            id=str(uuid.uuid4()),
            claim_id=claim.id,
            source_request_item_id=ri.id,
            declared_amount=ri.total_value,
        ))
        item_count += 1
    if item_count > 0:
        await db.flush()

    await log_audit(db, action="create_policy_claim", entity_type="PolicyClaim", entity_id=claim.id, user=user)
    return {"claim_id": claim.id, "claim_no": claim.claim_no, "status": claim.status,
            "policy_request_id": pr.id, "items_count": item_count}
