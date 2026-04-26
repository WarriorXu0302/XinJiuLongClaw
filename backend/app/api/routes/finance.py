"""
Finance API routes — CRUD for receipts, payments, expenses,
manufacturer settlements, payment requests; plus business endpoints
for allocation-confirm, expense approval/pay, receivables, and reconciliation.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentUser
from app.core.permissions import require_role
from app.models.base import PaymentRequestStatus, PaymentStatus
from app.models.customer import Receivable
from app.models.finance import (
    Expense,
    FinancePaymentRequest,
    ManufacturerSettlement,
    Payment,
    Receipt,
)
from app.models.order import Order
from app.models.product import Account
from app.schemas.finance import (
    ExpenseCreate,
    ExpenseResponse,
    ExpenseUpdate,
    ManufacturerSettlementCreate,
    ManufacturerSettlementResponse,
    ManufacturerSettlementUpdate,
    PaymentCreate,
    PaymentRequestCreate,
    PaymentRequestResponse,
    PaymentRequestUpdate,
    PaymentResponse,
    PaymentUpdate,
    ReceiptCreate,
    ReceiptResponse,
    ReceiptUpdate,
)
from app.services.audit_service import log_audit
from app.services.policy_service import confirm_settlement_allocation

router = APIRouter()


def _gen_no(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"{prefix}-{ts}-{short}"


# ═══════════════════════════════════════════════════════════════════
# Receipt CRUD
# ═══════════════════════════════════════════════════════════════════


@router.post("/receipts", response_model=ReceiptResponse, status_code=201)
async def create_receipt(body: ReceiptCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance", "salesman")
    # 收款强制进公司总资金池（master 现金账户）
    master_cash = (await db.execute(
        select(Account).where(
            Account.level == 'master',
            Account.account_type == 'cash',
        )
    )).scalar_one_or_none()
    if not master_cash:
        raise HTTPException(400, "未配置公司总资金池（level=master, account_type=cash），请先到账户管理创建")

    data = body.model_dump()
    data['account_id'] = master_cash.id  # 覆盖前端传入
    # P2c-1 后 Receipt.status 默认是 pending_confirmation，但这条 endpoint 是
    # finance/boss 直接建收款的快捷通道，建完立即动账（下面加 balance + fund_flow），
    # 必须把 Receipt 标为 confirmed，否则后续 confirm_payment 会把它当"待审"再加一次账。
    obj = Receipt(
        id=str(uuid.uuid4()), receipt_no=_gen_no("RC"),
        status="confirmed",
        confirmed_at=datetime.now(timezone.utc),
        confirmed_by=user.get("employee_id"),
        **data,
    )
    db.add(obj)
    await db.flush()

    master_cash.balance += obj.amount
    from app.api.routes.accounts import record_fund_flow
    await record_fund_flow(
        db, account_id=master_cash.id, flow_type='credit', amount=obj.amount,
        balance_after=master_cash.balance, related_type='receipt', related_id=obj.id,
        notes=f"收款 {obj.receipt_no}", created_by=user.get('employee_id'),
        brand_id=obj.brand_id,
    )

    if obj.order_id:
        order = await db.get(Order, obj.order_id)
        if order:
            total_received = (
                await db.execute(
                    select(func.coalesce(func.sum(Receipt.amount), 0))
                    .where(Receipt.order_id == obj.order_id)
                )
            ).scalar_one()
            prev_status = order.payment_status
            # 全额回款基准 = 订单应收（customer_paid_amount）
            # customer_pay/employee_pay: 26,550；company_pay: 19,500
            target_amount = order.customer_paid_amount or order.total_amount
            if Decimal(str(total_received)) >= target_amount:
                order.payment_status = PaymentStatus.FULLY_PAID
            elif total_received > 0:
                order.payment_status = PaymentStatus.PARTIALLY_PAID

            # 订单首次全额回款 → 自动生成一条 pending Commission（按品牌提成率 × 回款金额）
            if (prev_status != PaymentStatus.FULLY_PAID
                and order.payment_status == PaymentStatus.FULLY_PAID
                and order.salesman_id and order.brand_id):
                from app.models.user import Commission
                from app.models.payroll import EmployeeBrandPosition, BrandSalaryScheme
                # 幂等：同一订单不重复挂
                existed = (await db.execute(
                    select(Commission).where(Commission.order_id == order.id)
                )).scalar_one_or_none()
                if not existed:
                    # 取员工在该品牌的个性化提成率；没有就取品牌+岗位默认
                    ebp = (await db.execute(
                        select(EmployeeBrandPosition).where(
                            EmployeeBrandPosition.employee_id == order.salesman_id,
                            EmployeeBrandPosition.brand_id == order.brand_id,
                        )
                    )).scalar_one_or_none()
                    rate = None
                    if ebp and ebp.commission_rate is not None:
                        rate = Decimal(str(ebp.commission_rate))
                    else:
                        scheme = (await db.execute(
                            select(BrandSalaryScheme).where(
                                BrandSalaryScheme.brand_id == order.brand_id,
                                BrandSalaryScheme.position_code == (ebp.position_code if ebp else 'salesman'),
                            )
                        )).scalar_one_or_none()
                        if scheme:
                            rate = Decimal(str(scheme.commission_rate))
                    if rate and rate > 0:
                        # 提成基数 = 订单应收（公司实际拿到的钱）
                        # customer_pay/employee_pay → 26,550；company_pay → 19,500
                        comm_base = order.customer_paid_amount or order.total_amount
                        comm_amount = (Decimal(str(comm_base)) * rate).quantize(Decimal("0.01"))
                        db.add(Commission(
                            id=str(uuid.uuid4()),
                            employee_id=order.salesman_id,
                            brand_id=order.brand_id,
                            order_id=order.id,
                            commission_amount=comm_amount,
                            status='pending',
                            notes=f"订单{order.order_no} 基数¥{comm_base} × {rate*100}%（{order.settlement_mode}）",
                        ))
                        await db.flush()

                # 刷新本月 KPI（kpi_revenue + kpi_customers）
                try:
                    from app.models.payroll import AssessmentItem
                    from sqlalchemy import extract as _ext
                    now = datetime.now(timezone.utc)
                    period = f"{now.year}-{str(now.month).zfill(2)}"
                    items = (await db.execute(
                        select(AssessmentItem).where(
                            AssessmentItem.employee_id == order.salesman_id,
                            AssessmentItem.period == period,
                        )
                    )).scalars().all()
                    for it in items:
                        actual = None
                        if it.item_code == 'kpi_revenue':
                            actual = (await db.execute(
                                select(func.coalesce(func.sum(Receipt.amount), 0))
                                .select_from(Receipt).join(Order, Order.id == Receipt.order_id, isouter=True)
                                .where(
                                    Order.salesman_id == order.salesman_id,
                                    _ext("year", Receipt.receipt_date) == now.year,
                                    _ext("month", Receipt.receipt_date) == now.month,
                                )
                            )).scalar_one()
                        elif it.item_code == 'kpi_customers':
                            actual = (await db.execute(
                                select(func.count(func.distinct(Order.customer_id))).where(
                                    Order.salesman_id == order.salesman_id,
                                    _ext("year", Order.created_at) == now.year,
                                    _ext("month", Order.created_at) == now.month,
                                )
                            )).scalar_one()
                        if actual is not None:
                            it.actual_value = Decimal(str(actual))
                            if it.target_value and it.target_value > 0:
                                r = Decimal(str(actual)) / it.target_value
                            else:
                                r = Decimal("0")
                            it.completion_rate = r
                            it.earned_amount = (it.item_amount * r).quantize(Decimal("0.01")) if r >= Decimal("0.5") else Decimal("0")

                    # 销售目标里程碑：50% / 80% / 100% / 120%
                    from app.models.sales_target import SalesTarget
                    from app.models.user import User as _U
                    from app.services.notification_service import notify as _nt
                    targets = (await db.execute(
                        select(SalesTarget).where(
                            SalesTarget.target_level == 'employee',
                            SalesTarget.employee_id == order.salesman_id,
                            SalesTarget.target_year == now.year,
                            SalesTarget.target_month == now.month,
                        )
                    )).scalars().all()
                    for t in targets:
                        metric_actual = Decimal("0")
                        metric_label = '回款'
                        if t.bonus_metric == 'sales':
                            metric_label = '销售'
                            _s = (await db.execute(
                                select(func.coalesce(func.sum(Order.total_amount), 0)).where(
                                    Order.salesman_id == order.salesman_id,
                                    _ext("year", Order.created_at) == now.year,
                                    _ext("month", Order.created_at) == now.month,
                                )
                            )).scalar_one()
                            metric_actual = Decimal(str(_s))
                            target_val = t.sales_target
                        else:
                            _r = (await db.execute(
                                select(func.coalesce(func.sum(Receipt.amount), 0))
                                .select_from(Receipt).join(Order, Order.id == Receipt.order_id, isouter=True)
                                .where(
                                    Order.salesman_id == order.salesman_id,
                                    _ext("year", Receipt.receipt_date) == now.year,
                                    _ext("month", Receipt.receipt_date) == now.month,
                                )
                            )).scalar_one()
                            metric_actual = Decimal(str(_r))
                            target_val = t.receipt_target
                        if not target_val or target_val <= 0:
                            continue
                        rate = float(metric_actual / target_val)
                        # 本次新增金额 → 推算上次 rate（刚跨过门槛才推送）
                        prev_actual = metric_actual - Decimal(str(obj.amount)) if t.bonus_metric != 'sales' else metric_actual
                        prev_rate = float(prev_actual / target_val) if target_val > 0 else 0
                        for milestone, emoji in [(0.5, '🎯'), (0.8, '💪'), (1.0, '🎉'), (1.2, '🏆')]:
                            if prev_rate < milestone <= rate:
                                # 查该员工账号
                                u = (await db.execute(
                                    select(_U).where(_U.employee_id == order.salesman_id, _U.is_active == True)
                                )).scalar_one_or_none()
                                if u:
                                    await _nt(
                                        db, recipient_id=u.id,
                                        title=f"{emoji} {metric_label}目标达成 {int(milestone*100)}%",
                                        content=f"{now.year}-{str(now.month).zfill(2)} {metric_label}目标 ¥{float(target_val):,.0f}，当前 ¥{float(metric_actual):,.0f}，完成率 {rate*100:.1f}%",
                                        entity_type="SalesTarget", entity_id=t.id,
                                    )
                                break
                except Exception:
                    pass  # KPI 自动刷新失败不影响收款

    if obj.order_id:
        receivables = (
            await db.execute(
                select(Receivable)
                .where(Receivable.order_id == obj.order_id)
                .where(Receivable.status != "paid")
            )
        ).scalars().all()
        remaining = Decimal(str(obj.amount))
        for recv in receivables:
            if remaining <= 0:
                break
            can_apply = Decimal(str(recv.amount)) - Decimal(str(recv.paid_amount))
            applied = min(remaining, can_apply)
            recv.paid_amount = float(Decimal(str(recv.paid_amount)) + applied)
            if recv.paid_amount >= float(recv.amount):
                recv.status = "paid"
            else:
                recv.status = "partial"
            remaining -= applied
        # 防止静默吞款：收款多于应收时记 notes 警示
        if remaining > 0:
            obj.notes = (obj.notes or "") + f" [警告: 多收款 ¥{remaining} 未匹配到应收]"

    await db.flush()
    await log_audit(db, action="create_receipt", entity_type="Receipt", entity_id=obj.id, user=user)
    return obj


@router.get("/receipts")
async def list_receipts(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    from app.core.permissions import is_salesman
    base = select(Receipt)
    if brand_id:
        base = base.where(Receipt.brand_id == brand_id)
    # 业务员只看自己订单的收款
    if is_salesman(user) and user.get("employee_id"):
        base = base.join(Order, Order.id == Receipt.order_id).where(Order.salesman_id == user["employee_id"])
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(Receipt.created_at.desc()).offset(skip).limit(limit))).scalars().all()
    return {"items": rows, "total": total}


@router.get("/receipts/{receipt_id}", response_model=ReceiptResponse)
async def get_receipt(receipt_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Receipt, receipt_id)
    if obj is None:
        raise HTTPException(404, "Receipt not found")
    return obj


@router.put("/receipts/{receipt_id}", response_model=ReceiptResponse)
async def update_receipt(receipt_id: str, body: ReceiptUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    obj = await db.get(Receipt, receipt_id)
    if obj is None:
        raise HTTPException(404, "Receipt not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return obj


@router.delete("/receipts/{receipt_id}", status_code=204)
async def delete_receipt(receipt_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """删除 Receipt — 只允许删未动账的（pending_confirmation / rejected）。

    已 confirmed 的 Receipt 已加了 master balance 并写过 fund_flow，删掉会
    导致账务永久失衡（余额虚高 / fund_flow 孤儿）。要撤销已入账的收款必须
    走"反向凭证"流程（财务新建负数 Receipt），而不是 DELETE。
    """
    require_role(user, "boss", "finance")
    obj = await db.get(Receipt, receipt_id)
    if obj is None:
        raise HTTPException(404, "Receipt not found")
    if obj.status == "confirmed":
        raise HTTPException(
            400,
            f"收款 {obj.receipt_no} 已入账，不能删除。如需撤销请走反向凭证流程（新建负数收款）。",
        )
    # 删关联 fund_flow（保险起见，即便 pending 状态理论上没有流水）
    from app.models.fund_flow import FundFlow
    await db.execute(
        FundFlow.__table__.delete().where(
            FundFlow.related_type == 'receipt',
            FundFlow.related_id == obj.id,
        )
    )
    await db.delete(obj)
    await db.flush()
    await log_audit(db, action="delete_receipt", entity_type="Receipt",
                    entity_id=obj.id, user=user,
                    changes={"receipt_no": obj.receipt_no, "status_when_deleted": obj.status})


# ═══════════════════════════════════════════════════════════════════
# Payment CRUD
# ═══════════════════════════════════════════════════════════════════


@router.post("/payments", response_model=PaymentResponse, status_code=201)
async def create_payment(body: PaymentCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    if body.account_id:
        account = await db.get(Account, body.account_id)
        if account and account.balance < Decimal(str(body.amount)):
            raise HTTPException(400, f"账户余额不足：{account.name} 当前余额 ¥{account.balance}，需付 ¥{body.amount}")

    obj = Payment(id=str(uuid.uuid4()), payment_no=_gen_no("PY"), **body.model_dump())
    db.add(obj)
    await db.flush()

    if obj.account_id:
        account = await db.get(Account, obj.account_id)
        if account:
            account.balance -= obj.amount
            from app.api.routes.accounts import record_fund_flow
            await record_fund_flow(
                db, account_id=account.id, flow_type='debit', amount=obj.amount,
                balance_after=account.balance, related_type='payment', related_id=obj.id,
                notes=f"付款 {obj.payment_no}", created_by=user.get('employee_id'),
            )
            await db.flush()

    await log_audit(db, action="create_payment", entity_type="Payment", entity_id=obj.id, user=user)
    return obj


@router.get("/payments")
async def list_payments(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    base = select(Payment)
    if brand_id:
        base = base.where(Payment.brand_id == brand_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(Payment.created_at.desc()).offset(skip).limit(limit))).scalars().all()
    return {"items": rows, "total": total}


@router.get("/payments/{payment_id}", response_model=PaymentResponse)
async def get_payment(payment_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Payment, payment_id)
    if obj is None:
        raise HTTPException(404, "Payment not found")
    return obj


@router.put("/payments/{payment_id}", response_model=PaymentResponse)
async def update_payment(payment_id: str, body: PaymentUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    obj = await db.get(Payment, payment_id)
    if obj is None:
        raise HTTPException(404, "Payment not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return obj


@router.delete("/payments/{payment_id}", status_code=204)
async def delete_payment(payment_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """删除 Payment — Payment 代表已经付出去的钱，删掉会导致账户余额虚低。

    Payment 没有 status 字段区分草稿/已付，设计上每条都算已执行。
    只有 admin 能强删（走 /accounts/fund-flows 反向凭证更规范）。
    """
    require_role(user, "boss", "finance")
    if not user.get("is_admin"):
        raise HTTPException(
            400,
            "Payment 代表已付款记录，不能直接删除。"
            "如需撤销请在资金流水页建反向凭证，或联系管理员。",
        )
    obj = await db.get(Payment, payment_id)
    if obj is None:
        raise HTTPException(404, "Payment not found")
    # 删关联 fund_flow
    from app.models.fund_flow import FundFlow
    await db.execute(
        FundFlow.__table__.delete().where(
            FundFlow.related_type == 'payment',
            FundFlow.related_id == obj.id,
        )
    )
    await db.delete(obj)
    await db.flush()
    await log_audit(db, action="delete_payment", entity_type="Payment",
                    entity_id=obj.id, user=user,
                    changes={"payment_no": obj.payment_no, "amount": float(obj.amount)})


# ═══════════════════════════════════════════════════════════════════
# Expense CRUD + Approval + Pay
# ═══════════════════════════════════════════════════════════════════


@router.post("/expenses", response_model=ExpenseResponse, status_code=201)
async def create_expense(body: ExpenseCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    obj = Expense(id=str(uuid.uuid4()), expense_no=_gen_no("EX"), **body.model_dump())
    db.add(obj)
    await db.flush()
    return obj


@router.get("/expenses")
async def list_expenses(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    base = select(Expense)
    if brand_id:
        base = base.where(Expense.brand_id == brand_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(Expense.created_at.desc()).offset(skip).limit(limit))).scalars().all()
    return {"items": rows, "total": total}


@router.get("/expenses/{expense_id}", response_model=ExpenseResponse)
async def get_expense(expense_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(Expense, expense_id)
    if obj is None:
        raise HTTPException(404, "Expense not found")
    return obj


@router.put("/expenses/{expense_id}", response_model=ExpenseResponse)
async def update_expense(expense_id: str, body: ExpenseUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    obj = await db.get(Expense, expense_id)
    if obj is None:
        raise HTTPException(404, "Expense not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return obj


@router.delete("/expenses/{expense_id}", status_code=204)
async def delete_expense(expense_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """删除费用单 — 已付款的禁止删（会导致账户余额虚低）。"""
    require_role(user, "boss", "finance")
    obj = await db.get(Expense, expense_id)
    if obj is None:
        raise HTTPException(404, "Expense not found")
    if obj.status == PaymentRequestStatus.PAID or str(obj.status) == 'paid':
        raise HTTPException(
            400,
            f"费用单 {obj.expense_no} 已付款，不能直接删除。"
            "如需撤销请建反向凭证或联系管理员。",
        )
    await db.delete(obj)
    await db.flush()
    await log_audit(db, action="delete_expense", entity_type="Expense",
                    entity_id=obj.id, user=user,
                    changes={"expense_no": obj.expense_no, "status_when_deleted": str(obj.status)})


@router.post("/expenses/{expense_id}/approve", response_model=ExpenseResponse)
async def approve_expense(expense_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    obj = await db.get(Expense, expense_id)
    if obj is None:
        raise HTTPException(404, "Expense not found")
    if obj.status != "pending":
        raise HTTPException(400, f"报销单状态为 '{obj.status}'，只有 pending 可审批")
    obj.status = "approved"
    obj.approved_by = user.get("employee_id")
    await db.flush()
    await log_audit(db, action="approve_expense", entity_type="Expense", entity_id=obj.id, user=user)
    return obj


@router.post("/expenses/{expense_id}/reject", response_model=ExpenseResponse)
async def reject_expense(expense_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    obj = await db.get(Expense, expense_id)
    if obj is None:
        raise HTTPException(404, "Expense not found")
    if obj.status != "pending":
        raise HTTPException(400, f"报销单状态为 '{obj.status}'，只有 pending 可驳回")
    obj.status = "rejected"
    await db.flush()
    return obj


class ExpensePayRequest(BaseModel):
    payment_account_id: str


@router.post("/expenses/{expense_id}/pay", response_model=ExpenseResponse)
async def pay_expense(expense_id: str, body: ExpensePayRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    obj = await db.get(Expense, expense_id)
    if obj is None:
        raise HTTPException(404, "Expense not found")
    if obj.status != "approved":
        raise HTTPException(400, f"只有审批通过的报销单才能付款，当前状态: {obj.status}")
    account = await db.get(Account, body.payment_account_id)
    if account is None:
        raise HTTPException(404, "付款账户不存在")
    if account.balance < obj.amount:
        raise HTTPException(400, f"账户余额不足：{account.name} 余额 ¥{account.balance}，需付 ¥{obj.amount}")
    account.balance -= obj.amount
    obj.payment_account_id = body.payment_account_id
    obj.status = "paid"
    obj.payment_date = datetime.now(timezone.utc).date()
    from app.api.routes.accounts import record_fund_flow
    await record_fund_flow(
        db, account_id=account.id, flow_type='debit', amount=obj.amount,
        balance_after=account.balance, related_type='expense', related_id=obj.id,
        notes=f"报销付款 {obj.expense_no}", created_by=user.get('employee_id'),
    )
    await db.flush()
    await log_audit(db, action="pay_expense", entity_type="Expense", entity_id=obj.id, user=user)
    # 通知申请人
    if obj.applicant_id:
        from app.models.user import User
        from app.services.notification_service import notify
        applicant_user = (await db.execute(
            select(User).where(User.employee_id == obj.applicant_id)
        )).scalar_one_or_none()
        if applicant_user:
            await notify(db, recipient_id=applicant_user.id,
                title=f"报销已付款: {obj.expense_no}",
                content=f"您的报销 ¥{obj.amount} 已从 {account.name} 付款",
                entity_type="Expense", entity_id=obj.id)
    return obj


# ═══════════════════════════════════════════════════════════════════
# ManufacturerSettlement CRUD + allocation
# ═══════════════════════════════════════════════════════════════════


@router.post("/manufacturer-settlements", response_model=ManufacturerSettlementResponse, status_code=201)
async def create_settlement(body: ManufacturerSettlementCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    data = body.model_dump()
    if data.get("unsettled_amount") is None:
        data["unsettled_amount"] = data["settlement_amount"]
    obj = ManufacturerSettlement(id=str(uuid.uuid4()), settlement_no=_gen_no("MS"), **data)
    db.add(obj)
    await db.flush()
    return obj


@router.get("/manufacturer-settlements")
async def list_settlements(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    base = select(ManufacturerSettlement)
    if brand_id:
        base = base.where(ManufacturerSettlement.brand_id == brand_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(ManufacturerSettlement.created_at.desc()).offset(skip).limit(limit))).scalars().all()
    return {"items": rows, "total": total}


@router.get("/manufacturer-settlements/{settlement_id}", response_model=ManufacturerSettlementResponse)
async def get_settlement(settlement_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(ManufacturerSettlement, settlement_id)
    if obj is None:
        raise HTTPException(404, "ManufacturerSettlement not found")
    return obj


@router.put("/manufacturer-settlements/{settlement_id}", response_model=ManufacturerSettlementResponse)
async def update_settlement(settlement_id: str, body: ManufacturerSettlementUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    obj = await db.get(ManufacturerSettlement, settlement_id)
    if obj is None:
        raise HTTPException(404, "ManufacturerSettlement not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return obj


@router.post("/manufacturer-settlements/{settlement_id}/allocation-preview")
async def allocation_preview(settlement_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    from app.mcp.tools import AllocationPreviewRequest, allocate_settlement_to_claims
    # 该 API 权威路径：HTTP 层已通过 CurrentUser 鉴权；内部调用 MCP 版本时需手动注入 mcp_user
    db.info["mcp_user"] = user
    body = AllocationPreviewRequest(settlement_id=settlement_id)
    return await allocate_settlement_to_claims(body, db)


class AllocationConfirmRequest(BaseModel):
    claim_id: str
    allocated_amount: Decimal
    confirmed_by: str


class AllocationConfirmResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    claim_id: str
    settlement_id: str
    allocated_amount: Decimal
    confirmed_by: str | None
    confirmed_at: datetime | None


@router.post("/manufacturer-settlements/{settlement_id}/allocation-confirm", response_model=AllocationConfirmResponse)
async def allocation_confirm(settlement_id: str, body: AllocationConfirmRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    try:
        link = await confirm_settlement_allocation(
            db, settlement_id=settlement_id, claim_id=body.claim_id,
            allocated_amount=body.allocated_amount, confirmed_by=body.confirmed_by,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    await log_audit(db, action="allocation_confirm", entity_type="ClaimSettlementLink", entity_id=link.id, user=user)
    return link


# ═══════════════════════════════════════════════════════════════════
# Manufacturer reconciliation: Excel import
# ═══════════════════════════════════════════════════════════════════


class ReconciliationMatchedItem(BaseModel):
    excel_row: int
    billcode: str
    scheme_no: str | None
    memo: str
    amount: float
    match_type: str
    matched_request_id: str | None = None
    matched_settlement_id: str | None = None


class ReconciliationUnmatchedItem(BaseModel):
    excel_row: int
    billcode: str
    scheme_no: str | None
    memo: str
    amount: float
    reason: str


class ReconciliationResult(BaseModel):
    total_rows: int
    matched_count: int
    unmatched_count: int
    matched_amount: float
    unmatched_amount: float
    matched: list[ReconciliationMatchedItem]
    unmatched: list[ReconciliationUnmatchedItem]


@router.post("/manufacturer-settlements/import-excel", response_model=ReconciliationResult)
async def import_settlement_excel(user: CurrentUser, brand_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    import xlrd, os
    from app.models.product import Brand
    from app.models.policy import PolicyRequest

    brand = await db.get(Brand, brand_id)
    if brand is None:
        raise HTTPException(404, "Brand not found")

    file_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'docs', '2025年青花郎费用表2026-02-27 14_06_12.xlsx')
    if not os.path.exists(file_path):
        raise HTTPException(404, "Excel file not found")
    try:
        wb = xlrd.open_workbook(file_path)
        ws = wb.sheet_by_index(0)
    except Exception as e:
        raise HTTPException(400, f"无法读取 Excel: {e}")

    matched: list[ReconciliationMatchedItem] = []
    unmatched: list[ReconciliationUnmatchedItem] = []
    for r in range(2, ws.nrows):
        try:
            billcode = str(ws.cell_value(r, 1) or '').strip()
            scheme_no = str(ws.cell_value(r, 2) or '').strip() or None
            memo = str(ws.cell_value(r, 7) or '').strip()
            income = ws.cell_value(r, 8) or 0
            if not billcode and not memo: continue
            if not income or float(income) == 0: continue
            amt = abs(float(income))

            if scheme_no:
                pr = (await db.execute(select(PolicyRequest).where(PolicyRequest.scheme_no == scheme_no, PolicyRequest.brand_id == brand_id).limit(1))).scalar_one_or_none()
                if pr:
                    matched.append(ReconciliationMatchedItem(excel_row=r, billcode=billcode, scheme_no=scheme_no, memo=memo, amount=amt, match_type='scheme_no', matched_request_id=pr.id))
                    continue

            if billcode:
                ms = (await db.execute(select(ManufacturerSettlement).where(ManufacturerSettlement.settlement_no == billcode).limit(1))).scalar_one_or_none()
                if ms:
                    matched.append(ReconciliationMatchedItem(excel_row=r, billcode=billcode, scheme_no=scheme_no, memo=memo, amount=amt, match_type='billcode', matched_settlement_id=ms.id))
                    continue

            reasons = []
            if scheme_no: reasons.append(f"方案号 '{scheme_no}' 未匹配")
            if billcode: reasons.append(f"单据号 '{billcode}' 未匹配")
            if not scheme_no and not billcode: reasons.append("无方案号和单据号")
            unmatched.append(ReconciliationUnmatchedItem(excel_row=r, billcode=billcode, scheme_no=scheme_no, memo=memo, amount=amt, reason='; '.join(reasons)))
        except Exception:
            unmatched.append(ReconciliationUnmatchedItem(excel_row=r, billcode=str(ws.cell_value(r, 1) or ''), scheme_no=None, memo='', amount=0, reason="解析异常"))

    return ReconciliationResult(
        total_rows=ws.nrows - 2, matched_count=len(matched), unmatched_count=len(unmatched),
        matched_amount=sum(m.amount for m in matched), unmatched_amount=sum(u.amount for u in unmatched),
        matched=matched, unmatched=unmatched,
    )


# ═══════════════════════════════════════════════════════════════════
# PaymentRequest CRUD + confirm-payment
# ═══════════════════════════════════════════════════════════════════


@router.post("/payment-requests", response_model=PaymentRequestResponse, status_code=201)
async def create_payment_request(body: PaymentRequestCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    obj = FinancePaymentRequest(id=str(uuid.uuid4()), request_no=_gen_no("PR"), **body.model_dump())
    db.add(obj)
    await db.flush()
    return obj


@router.get("/payment-requests")
async def list_payment_requests(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    base = select(FinancePaymentRequest)
    if brand_id:
        base = base.where(FinancePaymentRequest.brand_id == brand_id)
    if status:
        base = base.where(FinancePaymentRequest.status == status)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(FinancePaymentRequest.created_at.desc()).offset(skip).limit(limit))).scalars().all()
    return {"items": rows, "total": total}


@router.get("/payment-requests/{request_id}", response_model=PaymentRequestResponse)
async def get_payment_request(request_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(FinancePaymentRequest, request_id)
    if obj is None:
        raise HTTPException(404, "PaymentRequest not found")
    return obj


@router.put("/payment-requests/{request_id}", response_model=PaymentRequestResponse)
async def update_payment_request(request_id: str, body: PaymentRequestUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    obj = await db.get(FinancePaymentRequest, request_id)
    if obj is None:
        raise HTTPException(404, "PaymentRequest not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    return obj


class ConfirmPaymentBody(BaseModel):
    payment_account_id: str | None = None  # 覆盖时必须是 project cash
    payment_voucher_urls: list[str] = []
    signed_photo_urls: list[str] = []


@router.post("/payment-requests/{request_id}/confirm-payment", response_model=PaymentRequestResponse)
async def confirm_payment(
    request_id: str,
    body: ConfirmPaymentBody,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "finance")
    obj = await db.get(FinancePaymentRequest, request_id)
    if obj is None:
        raise HTTPException(404, "PaymentRequest not found")
    if obj.status == PaymentRequestStatus.PAID:
        raise HTTPException(400, "PaymentRequest is already paid")
    if obj.status == PaymentRequestStatus.CANCELLED:
        raise HTTPException(400, "PaymentRequest is cancelled")

    # 凭证：转款凭证和签收照至少一种（通常都要，但允许二选一）
    if not body.payment_voucher_urls and not body.signed_photo_urls:
        raise HTTPException(400, "请至少上传转款凭证或签收照片")

    # 付款账户强制为品牌现金账户（F 类专款专用于订货）
    account_id = body.payment_account_id or obj.payable_account_id
    if not account_id:
        raise HTTPException(400, "请指定付款账户（品牌现金账户）")
    account = await db.get(Account, account_id)
    if not account:
        raise HTTPException(400, "付款账户不存在")
    if account.account_type != 'cash' or account.level != 'project':
        raise HTTPException(400, "兑付付款必须从品牌现金账户扣款（非 F 类/非总账）")
    if account.balance < obj.amount:
        raise HTTPException(400, f"账户余额不足：{account.name} 余额 ¥{account.balance}，需付 ¥{obj.amount}")

    # 扣账户 + 流水
    account.balance -= obj.amount
    from app.api.routes.accounts import record_fund_flow
    await record_fund_flow(
        db, account_id=account.id, flow_type='debit', amount=obj.amount,
        balance_after=account.balance, related_type='advance_refund', related_id=obj.id,
        notes=f"垫付返还 {obj.request_no}", created_by=user.get('employee_id'),
    )

    obj.payable_account_id = account.id
    obj.payment_voucher_urls = body.payment_voucher_urls or None
    obj.signed_photo_urls = body.signed_photo_urls or None
    obj.status = PaymentRequestStatus.PAID
    obj.paid_at = datetime.now(timezone.utc)

    # 通知被返还的业务员/客户
    from app.services.notification_service import notify
    from app.models.user import User as _U
    payee_emp_id = obj.payee_employee_id
    if payee_emp_id:
        u = (await db.execute(
            select(_U).where(_U.employee_id == payee_emp_id, _U.is_active == True)
        )).scalar_one_or_none()
        if u:
            await notify(
                db, recipient_id=u.id,
                title=f"垫付返还 {obj.request_no} 已付款",
                content=f"金额 ¥{obj.amount}，请在「我的」查看凭证。",
                entity_type="FinancePaymentRequest", entity_id=obj.id,
            )

    await db.flush()
    await log_audit(db, action="confirm_payment", entity_type="FinancePaymentRequest", entity_id=obj.id, user=user)
    return obj


# ═══════════════════════════════════════════════════════════════════
# Receivables (read-only list)
# ═══════════════════════════════════════════════════════════════════


class ReceivableResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    receivable_no: str
    customer_id: str
    order_id: str | None = None
    amount: float
    paid_amount: float
    due_date: str | None = None
    status: str
    created_at: datetime


@router.get("/receivables")
async def list_receivables(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    status: str | None = Query(None),
    customer_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    from app.core.permissions import is_salesman
    base = select(Receivable)
    if brand_id:
        base = base.where(Receivable.brand_id == brand_id)
    if status:
        base = base.where(Receivable.status == status)
    if customer_id:
        base = base.where(Receivable.customer_id == customer_id)
    # 业务员过滤
    if is_salesman(user) and user.get("employee_id"):
        base = base.join(Order, Order.id == Receivable.order_id).where(Order.salesman_id == user["employee_id"])
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(Receivable.created_at.desc()).offset(skip).limit(limit))).scalars().all()
    return {"items": rows, "total": total}

@router.get("/receivables/aging")
async def receivables_aging(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """应收账龄分析：按 0-30 / 30-60 / 60-90 / 90+ 天分档"""
    from datetime import date as _d
    from app.core.permissions import is_salesman

    stmt = select(Receivable).where(Receivable.status != "paid")
    if brand_id:
        stmt = stmt.where(Receivable.brand_id == brand_id)
    if is_salesman(user) and user.get("employee_id"):
        stmt = stmt.join(Order, Order.id == Receivable.order_id).where(Order.salesman_id == user["employee_id"])
    rows = (await db.execute(stmt)).scalars().all()

    today = _d.today()
    buckets = {"0-30": 0.0, "30-60": 0.0, "60-90": 0.0, "90+": 0.0}
    bucket_counts = {"0-30": 0, "30-60": 0, "60-90": 0, "90+": 0}
    bucket_details = {"0-30": [], "30-60": [], "60-90": [], "90+": []}
    total_outstanding = 0.0
    for r in rows:
        remaining = float((r.amount or 0) - (r.paid_amount or 0))
        if remaining <= 0:
            continue
        total_outstanding += remaining
        base_date = r.due_date or (r.created_at.date() if r.created_at else today)
        days = (today - base_date).days
        if days < 30:
            bucket = "0-30"
        elif days < 60:
            bucket = "30-60"
        elif days < 90:
            bucket = "60-90"
        else:
            bucket = "90+"
        buckets[bucket] += remaining
        bucket_counts[bucket] += 1
        # 取前 50 条明细
        if len(bucket_details[bucket]) < 50:
            # 获取客户名
            from app.models.customer import Customer as _C
            cust = await db.get(_C, r.customer_id) if r.customer_id else None
            bucket_details[bucket].append({
                "receivable_no": r.receivable_no,
                "customer_name": cust.name if cust else '-',
                "amount": float(r.amount or 0),
                "paid_amount": float(r.paid_amount or 0),
                "remaining": remaining,
                "due_date": str(r.due_date) if r.due_date else None,
                "days_overdue": days,
                "order_id": r.order_id,
            })

    return {
        "total_outstanding": total_outstanding,
        "buckets": [
            {"label": k, "amount": buckets[k], "count": bucket_counts[k],
             "percentage": round(buckets[k] / total_outstanding * 100, 2) if total_outstanding > 0 else 0,
             "details": bucket_details[k]}
            for k in ["0-30", "30-60", "60-90", "90+"]
        ],
    }
