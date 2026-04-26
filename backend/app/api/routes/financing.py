"""
Financing Order API — create orders, submit repayment/return for approval.

Flow:
  1. Create financing order → financing account balance goes UP (liability)
  2. Submit repayment (from AccountOverview transfer) → pending approval
  3. Approve repayment → deduct brand cash account, decrease financing balance
  4. Return warehouse (退仓) → manufacturer pays bank, company pays interest only
"""
import uuid
from datetime import date as date_type, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.base import FinancingOrderStatus
from app.models.financing import FinancingOrder, FinancingRepayment
from app.models.product import Account
from app.services.audit_service import log_audit

router = APIRouter()


def _gen_no(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"{prefix}-{ts}-{short}"


def _calc_interest(
    amount: Decimal, annual_rate: Decimal | None,
    start_date: date_type, end_date: date_type,
) -> tuple[Decimal, int]:
    """interest = amount × (rate/100) × days / 365.  Returns (interest, days)."""
    days = (end_date - start_date).days + 1  # inclusive
    if days < 1:
        days = 1
    if not annual_rate or annual_rate <= 0:
        return Decimal("0.00"), days
    interest = (amount * annual_rate / Decimal("100") * days / Decimal("365")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return interest, days


# ═══════════════════════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════════════════════

class FinancingOrderCreate(BaseModel):
    brand_id: str
    amount: float
    interest_rate: Optional[float] = None
    start_date: date_type
    maturity_date: Optional[date_type] = None
    total_interest: float = 0
    bank_name: Optional[str] = None
    bank_loan_no: Optional[str] = None
    manufacturer_notes: Optional[str] = None
    notes: Optional[str] = None


class FinancingOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    order_no: str
    brand_id: str
    financing_account_id: str
    amount: float
    interest_rate: Optional[float] = None
    start_date: date_type
    maturity_date: Optional[date_type] = None
    total_interest: float
    repaid_principal: float
    repaid_interest: float
    outstanding_balance: float
    status: str
    bank_name: Optional[str] = None
    bank_loan_no: Optional[str] = None
    manufacturer_notes: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


class RepaymentItemInput(BaseModel):
    product_id: str
    quantity: int
    unit_price: float


class SubmitRepaymentRequest(BaseModel):
    principal_amount: float
    payment_account_id: str
    f_class_amount: float = 0
    f_class_account_id: Optional[str] = None
    # When f_class_amount > 0 → manufacturer ships goods → need PO details
    supplier_id: Optional[str] = None
    warehouse_id: Optional[str] = None
    items: list[RepaymentItemInput] = []
    notes: Optional[str] = None


class RepaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    repayment_no: str
    financing_order_id: str
    repayment_type: str
    status: str
    repayment_date: date_type
    interest_days: int
    principal_amount: float
    interest_amount: float
    total_amount: float
    payment_account_id: str
    f_class_amount: float = 0
    f_class_account_id: Optional[str] = None
    purchase_order_id: Optional[str] = None
    reject_reason: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


class InterestPreview(BaseModel):
    principal_amount: float
    interest_amount: float
    interest_days: int
    total_cash_deduction: float


# ═══════════════════════════════════════════════════════════════════
# Fixed-path routes FIRST (before /{order_id} wildcard)
# ═══════════════════════════════════════════════════════════════════

@router.post("", response_model=FinancingOrderResponse, status_code=201)
async def create_financing_order(
    body: FinancingOrderCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """Create a financing order → increase financing account balance (liability)."""
    require_role(user, "boss", "finance")
    amount = Decimal(str(body.amount))
    if amount <= 0:
        raise HTTPException(400, "融资金额必须大于0")

    stmt = select(Account).where(
        Account.brand_id == body.brand_id, Account.account_type == "financing",
        Account.level == "project", Account.is_active == True,
    )
    fin_acc = (await db.execute(stmt)).scalar_one_or_none()
    if not fin_acc:
        raise HTTPException(400, "该品牌没有融资账户，请先创建品牌")

    order = FinancingOrder(
        id=str(uuid.uuid4()), order_no=_gen_no("FN"), brand_id=body.brand_id,
        financing_account_id=fin_acc.id, amount=amount,
        interest_rate=Decimal(str(body.interest_rate)) if body.interest_rate else None,
        start_date=body.start_date, maturity_date=body.maturity_date,
        total_interest=Decimal(str(body.total_interest)), outstanding_balance=amount,
        bank_name=body.bank_name, bank_loan_no=body.bank_loan_no,
        manufacturer_notes=body.manufacturer_notes, notes=body.notes,
        created_by=user.get("employee_id"),
    )
    db.add(order)
    fin_acc.balance += amount

    from app.api.routes.accounts import record_fund_flow
    await record_fund_flow(
        db, account_id=fin_acc.id, flow_type="financing_drawdown", amount=amount,
        balance_after=fin_acc.balance, related_type="financing_order", related_id=order.id,
        notes=f"融资放款 {order.order_no} 本金 ¥{amount}",
        created_by=user.get("employee_id"), brand_id=body.brand_id,
    )
    await db.flush()
    await log_audit(db, action="create_financing_order", entity_type="FinancingOrder",
                    entity_id=order.id, changes={"amount": float(amount)}, user=user)
    return order


@router.get("")
async def list_financing_orders(
    user: CurrentUser, brand_id: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    base = select(FinancingOrder)
    if brand_id:
        base = base.where(FinancingOrder.brand_id == brand_id)
    if status:
        base = base.where(FinancingOrder.status == status)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(FinancingOrder.created_at.desc()).offset(skip).limit(limit))).scalars().all()
    return {"items": rows, "total": total}


@router.get("/pending-repayments", response_model=list[RepaymentResponse])
async def list_pending_repayments(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(FinancingRepayment)
        .where(FinancingRepayment.status == "pending")
        .order_by(FinancingRepayment.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().all()


@router.post("/repayments/{repayment_id}/approve")
async def approve_repayment(
    repayment_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    """Approve → deduct brand cash account. Auto-reject if insufficient."""
    require_role(user, "boss")
    # 锁 repayment 行，避免同一 repayment 被两个 approve 并发处理
    rep = (await db.execute(
        select(FinancingRepayment).where(FinancingRepayment.id == repayment_id).with_for_update()
    )).scalar_one_or_none()
    if not rep:
        raise HTTPException(404, "还款申请不存在")
    if rep.status != "pending":
        raise HTTPException(400, f"状态为 '{rep.status}'，不是待审批")

    # 锁 order 行：防止多笔 pending 并发 approve 时 `order.repaid_principal +=` 覆盖丢一笔
    order = (await db.execute(
        select(FinancingOrder).where(FinancingOrder.id == rep.financing_order_id).with_for_update()
    )).scalar_one_or_none()
    if not order:
        raise HTTPException(400, "融资订单不存在")

    pay_acc = await db.get(Account, rep.payment_account_id)
    if not pay_acc:
        raise HTTPException(400, "现金账户不存在")
    # 跨品牌校验：防止拿别品牌现金账户还本品牌融资
    if pay_acc.brand_id and pay_acc.brand_id != order.brand_id:
        raise HTTPException(400, "现金账户品牌与融资订单品牌不一致，拒绝跨品牌还款")

    from app.api.routes.accounts import record_fund_flow
    is_return = rep.repayment_type == "return_warehouse"
    cash_needed = rep.interest_amount if is_return else (rep.principal_amount + rep.interest_amount)

    # Auto-reject if cash insufficient
    if pay_acc.balance < cash_needed:
        rep.status = "rejected"
        rep.reject_reason = f"现金账户不够，驳回申请（余额 ¥{pay_acc.balance}，需 ¥{cash_needed}）"
        rep.approved_by = user.get("employee_id")
        await db.flush()
        return {"message": rep.reject_reason, "status": "rejected"}

    # F 类结算预校验（以前是静默跳过 → 会让现金/PO/order 已更新但 F 类未扣，账务永久失衡）
    f_acc = None
    if rep.f_class_amount and rep.f_class_amount > 0:
        if not rep.f_class_account_id:
            raise HTTPException(400, "F类金额 > 0 但未指定 F 类账户")
        f_acc = await db.get(Account, rep.f_class_account_id)
        if not f_acc:
            raise HTTPException(400, "F 类账户不存在")
        if f_acc.brand_id and f_acc.brand_id != order.brand_id:
            raise HTTPException(400, "F 类账户品牌与融资订单不一致")
        if f_acc.balance < rep.f_class_amount:
            raise HTTPException(400,
                f"F类账户余额不足：¥{f_acc.balance} < 需扣 ¥{rep.f_class_amount}")

    # 再校验剩余本金（并发已被锁拦住，这里仅兜底）
    if not is_return and rep.principal_amount > order.outstanding_balance:
        raise HTTPException(400,
            f"还款本金 ¥{rep.principal_amount} 超过未还余额 ¥{order.outstanding_balance}（可能被其他并发还款已占用）")

    # 1. Deduct cash
    pay_acc.balance -= cash_needed
    await record_fund_flow(
        db, account_id=pay_acc.id, flow_type="debit", amount=cash_needed,
        balance_after=pay_acc.balance, related_type="financing_repayment", related_id=rep.id,
        notes=f"{'退仓利息' if is_return else '融资还款'} {order.order_no} 本金¥{rep.principal_amount} 利息¥{rep.interest_amount}",
        created_by=user.get("employee_id"), brand_id=order.brand_id,
    )

    # 2. Decrease financing balance by principal
    fin_acc = await db.get(Account, order.financing_account_id)
    if fin_acc and rep.principal_amount > 0:
        fin_acc.balance -= rep.principal_amount
        await record_fund_flow(
            db, account_id=fin_acc.id, flow_type="financing_repayment",
            amount=rep.principal_amount, balance_after=fin_acc.balance,
            related_type="financing_repayment", related_id=rep.id,
            notes=f"{'退仓销账' if is_return else '融资还本'} {order.order_no} ¥{rep.principal_amount}",
            created_by=user.get("employee_id"), brand_id=order.brand_id,
        )

    # 3. F-class settlement（前面已预校验，此处必定扣得动）
    if f_acc is not None:
        f_acc.balance -= rep.f_class_amount
        await record_fund_flow(
            db, account_id=f_acc.id, flow_type="debit", amount=rep.f_class_amount,
            balance_after=f_acc.balance, related_type="financing_repayment", related_id=rep.id,
            notes=f"融资带出F类 {order.order_no} ¥{rep.f_class_amount}",
            created_by=user.get("employee_id"), brand_id=order.brand_id,
        )

    # TODO: 退仓(return_warehouse) 场景应从主仓出库对应货物，抵消本金。
    # 目前 FinancingRepayment 无 return_product_id/return_quantity 字段，
    # 实际出库由业务员另行手工操作（主仓 direct-outbound）。后续可补字段统一处理。

    # 4. Update order
    order.repaid_principal += rep.principal_amount
    order.repaid_interest += rep.interest_amount
    order.outstanding_balance = order.amount - order.repaid_principal
    if order.outstanding_balance <= 0:
        order.status = FinancingOrderStatus.FULLY_REPAID
    elif is_return:
        order.status = "returned"
    elif order.repaid_principal > 0:
        order.status = FinancingOrderStatus.PARTIALLY_REPAID

    rep.status = "approved"
    rep.approved_by = user.get("employee_id")

    # If linked PO exists, mark as paid (ready for receiving)
    if rep.purchase_order_id:
        from app.models.purchase import PurchaseOrder
        po = await db.get(PurchaseOrder, rep.purchase_order_id)
        if po:
            po.status = "paid"
            po.approved_by = user.get("employee_id")

    await db.flush()
    await log_audit(db, action="approve_financing_repayment", entity_type="FinancingOrder",
                    entity_id=order.id, changes={"principal": float(rep.principal_amount),
                    "interest": float(rep.interest_amount), "type": rep.repayment_type}, user=user)
    label = "退仓" if is_return else "还款"
    return {"message": f"融资{label}审批通过，已从现金账户扣款 ¥{cash_needed}", "status": "approved"}


@router.post("/repayments/{repayment_id}/reject")
async def reject_repayment(
    repayment_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss")
    rep = await db.get(FinancingRepayment, repayment_id)
    if not rep:
        raise HTTPException(404, "还款申请不存在")
    if rep.status != "pending":
        raise HTTPException(400, f"状态为 '{rep.status}'，不是待审批")
    rep.status = "rejected"
    rep.reject_reason = "人工驳回"
    rep.approved_by = user.get("employee_id")
    # Cancel linked PO if exists
    if rep.purchase_order_id:
        from app.models.purchase import PurchaseOrder
        po = await db.get(PurchaseOrder, rep.purchase_order_id)
        if po:
            po.status = "cancelled"
    await db.flush()
    return {"message": "已驳回"}


# ═══════════════════════════════════════════════════════════════════
# /{order_id} routes (wildcard — must come AFTER fixed paths)
# ═══════════════════════════════════════════════════════════════════

@router.get("/{order_id}", response_model=FinancingOrderResponse)
async def get_financing_order(order_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    order = await db.get(FinancingOrder, order_id)
    if order is None:
        raise HTTPException(404, "融资订单不存在")
    return order


@router.get("/{order_id}/calc-interest", response_model=InterestPreview)
async def calc_interest_preview(
    order_id: str, principal: float = Query(...),
    user: CurrentUser = None, db: AsyncSession = Depends(get_db),
):
    """Preview interest for frontend auto-calculation."""
    order = await db.get(FinancingOrder, order_id)
    if order is None:
        raise HTTPException(404, "融资订单不存在")
    amt = Decimal(str(principal))
    today = datetime.now(timezone.utc).date()
    interest, days = _calc_interest(amt, order.interest_rate, order.start_date, today)
    return InterestPreview(
        principal_amount=float(amt), interest_amount=float(interest),
        interest_days=days, total_cash_deduction=float(amt + interest),
    )


@router.post("/{order_id}/submit-repayment", response_model=RepaymentResponse, status_code=201)
async def submit_repayment(
    order_id: str, body: SubmitRepaymentRequest, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Submit financing repayment for approval. Auto-calculates interest."""
    require_role(user, "boss", "finance")
    order = await db.get(FinancingOrder, order_id)
    if order is None:
        raise HTTPException(404, "融资订单不存在")
    if order.status == FinancingOrderStatus.FULLY_REPAID:
        raise HTTPException(400, "该融资订单已全部还清")

    principal = Decimal(str(body.principal_amount))
    if principal <= 0:
        raise HTTPException(400, "还款本金必须大于0")
    if principal > order.outstanding_balance:
        raise HTTPException(400, f"还款本金 ¥{principal} 超过未还余额 ¥{order.outstanding_balance}")

    pay_acc = await db.get(Account, body.payment_account_id)
    if not pay_acc or pay_acc.account_type != "cash":
        raise HTTPException(400, "请选择现金账户")

    today = datetime.now(timezone.utc).date()
    interest, days = _calc_interest(principal, order.interest_rate, order.start_date, today)
    f_class_amt = Decimal(str(body.f_class_amount))

    repayment = FinancingRepayment(
        id=str(uuid.uuid4()), repayment_no=_gen_no("FR"),
        financing_order_id=order.id, repayment_type="normal", status="pending",
        repayment_date=today, interest_days=days,
        principal_amount=principal, interest_amount=interest,
        total_amount=principal + interest + f_class_amt,
        payment_account_id=body.payment_account_id,
        f_class_amount=f_class_amt, f_class_account_id=body.f_class_account_id,
        notes=body.notes, created_by=user.get("employee_id"),
    )
    db.add(repayment)

    # F-class > 0 means manufacturer ships goods → create linked PO
    if f_class_amt > 0 and body.items:
        if not body.supplier_id or not body.warehouse_id:
            raise HTTPException(400, "F类发货需要选择供应商和仓库")

        from app.models.purchase import PurchaseOrder, PurchaseOrderItem
        po_total = Decimal("0")
        po = PurchaseOrder(
            id=str(uuid.uuid4()), po_no=_gen_no("PO"),
            brand_id=order.brand_id, supplier_id=body.supplier_id,
            warehouse_id=body.warehouse_id,
            cash_amount=Decimal("0"), f_class_amount=f_class_amt,
            financing_amount=principal, financing_account_id=order.financing_account_id,
            financing_repayment_id=repayment.id,
            status="financing_pending",
            notes=f"融资还款发货 {repayment.repayment_no}",
        )
        for it in body.items:
            poi = PurchaseOrderItem(
                id=str(uuid.uuid4()), po_id=po.id,
                product_id=it.product_id, quantity=it.quantity,
                unit_price=Decimal(str(it.unit_price)),
            )
            po.items.append(poi)
            po_total += Decimal(str(it.unit_price)) * it.quantity
        po.total_amount = po_total
        db.add(po)
        repayment.purchase_order_id = po.id

    await db.flush()
    return repayment


@router.post("/{order_id}/submit-return", response_model=RepaymentResponse, status_code=201)
async def submit_return_warehouse(
    order_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    """退仓: manufacturer pays bank, company pays remaining interest only."""
    require_role(user, "boss", "finance")
    order = await db.get(FinancingOrder, order_id)
    if order is None:
        raise HTTPException(404, "融资订单不存在")
    if order.status == FinancingOrderStatus.FULLY_REPAID:
        raise HTTPException(400, "已全部还清，无需退仓")

    remaining = order.outstanding_balance
    today = datetime.now(timezone.utc).date()
    interest, days = _calc_interest(remaining, order.interest_rate, order.start_date, today)

    # Find brand's cash account
    stmt = select(Account).where(
        Account.brand_id == order.brand_id, Account.account_type == "cash",
        Account.level == "project", Account.is_active == True,
    )
    cash_acc = (await db.execute(stmt)).scalar_one_or_none()
    if not cash_acc:
        raise HTTPException(400, "该品牌没有现金账户")

    repayment = FinancingRepayment(
        id=str(uuid.uuid4()), repayment_no=_gen_no("RT"),
        financing_order_id=order.id, repayment_type="return_warehouse", status="pending",
        repayment_date=today, interest_days=days,
        principal_amount=remaining, interest_amount=interest,
        total_amount=interest,  # company only pays interest
        payment_account_id=cash_acc.id,
        notes=f"退仓：厂家代还本金 ¥{remaining}，公司承担利息 ¥{interest}（{days}天）",
        created_by=user.get("employee_id"),
    )
    db.add(repayment)
    await db.flush()
    return repayment


@router.get("/{order_id}/repayments", response_model=list[RepaymentResponse])
async def list_repayments(order_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    order = await db.get(FinancingOrder, order_id)
    if order is None:
        raise HTTPException(404, "融资订单不存在")
    stmt = (
        select(FinancingRepayment)
        .where(FinancingRepayment.financing_order_id == order_id)
        .order_by(FinancingRepayment.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().all()
