"""
Dashboard API — summary statistics with per-brand breakdown.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models.base import PolicyRequestStatus
from app.models.inventory import Inventory, StockOutAllocation
from app.models.order import Order, OrderItem
from app.models.policy import PolicyClaim, PolicyRequest
from app.models.policy_request_item import PolicyRequestItem
from app.models.inspection import InspectionCase
from app.models.finance import Expense
from app.models.expense_claim import ExpenseClaim
from app.models.product import Account, Brand, Product

router = APIRouter()

LOW_STOCK_THRESHOLD = 10


class BrandKPI(BaseModel):
    brand_id: str
    brand_name: str
    today_order_count: int = 0
    pending_policy_count: int = 0
    unsettled_claim_amount: float = 0
    inventory_value: float = 0
    account_balance: float = 0


class DashboardSummary(BaseModel):
    today_order_count: int
    pending_policy_count: int
    low_stock_count: int
    unsettled_claim_amount: float
    total_inventory_value: float
    by_brand: list[BrandKPI] = []


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    today_start = datetime.combine(date.today(), datetime.min.time())

    today_order_count = (
        await db.execute(
            select(func.count(Order.id)).where(Order.created_at >= today_start)
        )
    ).scalar_one()

    pending_policy_count = (
        await db.execute(
            select(func.count(PolicyRequest.id)).where(
                PolicyRequest.status.in_([
                    PolicyRequestStatus.PENDING_INTERNAL,
                    PolicyRequestStatus.PENDING_EXTERNAL,
                ])
            )
        )
    ).scalar_one()

    low_stock_count = (
        await db.execute(
            select(func.count()).select_from(Inventory).where(
                Inventory.quantity <= LOW_STOCK_THRESHOLD,
                Inventory.quantity > 0,
            )
        )
    ).scalar_one()

    unsettled_claim_amount = (
        await db.execute(
            select(func.coalesce(func.sum(PolicyClaim.unsettled_amount), 0)).where(
                PolicyClaim.unsettled_amount > 0
            )
        )
    ).scalar_one()

    # Per-brand breakdown
    brands = (await db.execute(select(Brand).order_by(Brand.code))).scalars().all()
    brand_kpis = []
    for b in brands:
        bk = BrandKPI(brand_id=b.id, brand_name=b.name)

        bk.today_order_count = (
            await db.execute(
                select(func.count(Order.id)).where(
                    Order.created_at >= today_start,
                    Order.brand_id == b.id,
                )
            )
        ).scalar_one()

        bk.pending_policy_count = (
            await db.execute(
                select(func.count(PolicyRequest.id)).where(
                    PolicyRequest.status.in_([
                        PolicyRequestStatus.PENDING_INTERNAL,
                        PolicyRequestStatus.PENDING_EXTERNAL,
                    ]),
                    PolicyRequest.brand_id == b.id,
                )
            )
        ).scalar_one()

        bk.unsettled_claim_amount = float((
            await db.execute(
                select(func.coalesce(func.sum(PolicyClaim.unsettled_amount), 0)).where(
                    PolicyClaim.unsettled_amount > 0,
                    PolicyClaim.brand_id == b.id,
                )
            )
        ).scalar_one())

        # Inventory value: sum(quantity * cost_price) for products of this brand
        bk.inventory_value = float((
            await db.execute(
                select(func.coalesce(func.sum(Inventory.quantity * Inventory.cost_price), 0))
                .join(Product, Inventory.product_id == Product.id)
                .where(Product.brand_id == b.id, Inventory.quantity > 0)
            )
        ).scalar_one())

        # Account balance: sum of project-level account balances for this brand
        bk.account_balance = float((
            await db.execute(
                select(func.coalesce(func.sum(Account.balance), 0)).where(
                    Account.brand_id == b.id,
                    Account.level == "project",
                )
            )
        ).scalar_one())

        brand_kpis.append(bk)

    # Global inventory value
    total_inventory_value = float((
        await db.execute(
            select(func.coalesce(func.sum(Inventory.quantity * Inventory.cost_price), 0))
            .where(Inventory.quantity > 0)
        )
    ).scalar_one())

    return DashboardSummary(
        today_order_count=today_order_count,
        pending_policy_count=pending_policy_count,
        low_stock_count=low_stock_count,
        unsettled_claim_amount=float(unsettled_claim_amount),
        total_inventory_value=total_inventory_value,
        by_brand=brand_kpis,
    )


class ProfitItem(BaseModel):
    category: str
    label: str
    amount: float
    direction: str  # income / expense


class ProfitSummaryResponse(BaseModel):
    total_income: float
    total_expense: float
    net_profit: float
    items: list[ProfitItem]


@router.get("/profit-summary", response_model=ProfitSummaryResponse)
async def profit_summary(
    user: CurrentUser,
    brand_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate profit/loss from all modules."""
    items: list[ProfitItem] = []

    # Date filters
    d_from = datetime.strptime(date_from, '%Y-%m-%d') if date_from else datetime(2020, 1, 1)
    d_to = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59) if date_to else datetime(2099, 12, 31)

    # --- 1. 订单销售利润（company_pay 按 deal_unit_price 算毛利；其他按指导价 unit_price）---
    from sqlalchemy import case as _case
    sell_price = _case(
        (Order.settlement_mode == 'company_pay', func.coalesce(Order.deal_unit_price, OrderItem.unit_price)),
        else_=OrderItem.unit_price,
    )
    order_q = select(
        func.coalesce(func.sum(
            (sell_price - func.coalesce(StockOutAllocation.allocated_cost_price, OrderItem.unit_price)) * StockOutAllocation.allocated_quantity
        ), 0)
    ).select_from(OrderItem).outerjoin(
        StockOutAllocation, StockOutAllocation.order_item_id == OrderItem.id
    ).join(Order, Order.id == OrderItem.order_id).where(
        Order.created_at.between(d_from, d_to)
    )
    if brand_id:
        order_q = order_q.where(Order.brand_id == brand_id)
    sales_profit = float((await db.execute(order_q)).scalar_one())
    items.append(ProfitItem(category='sales', label='订单销售利润', amount=sales_profit, direction='income' if sales_profit >= 0 else 'expense'))

    # --- 2. 政策兑付盈利 ---
    policy_profit_q = select(func.coalesce(func.sum(PolicyRequestItem.profit_loss), 0)).join(
        PolicyRequest, PolicyRequest.id == PolicyRequestItem.policy_request_id
    ).where(PolicyRequestItem.profit_loss > 0, PolicyRequest.created_at.between(d_from, d_to))
    if brand_id:
        policy_profit_q = policy_profit_q.where(PolicyRequest.brand_id == brand_id)
    policy_profit = float((await db.execute(policy_profit_q)).scalar_one())
    items.append(ProfitItem(category='policy_profit', label='政策兑付盈利', amount=policy_profit, direction='income'))

    # --- 3. 稽查清理盈利（只算已执行的案件，按执行时间过滤）---
    insp_profit_q = select(func.coalesce(func.sum(InspectionCase.profit_loss), 0)).where(
        InspectionCase.profit_loss > 0,
        InspectionCase.status.in_(('executed', 'closed')),
        InspectionCase.closed_at.between(d_from, d_to),
    )
    if brand_id:
        insp_profit_q = insp_profit_q.where(InspectionCase.brand_id == brand_id)
    insp_profit = float((await db.execute(insp_profit_q)).scalar_one())
    items.append(ProfitItem(category='inspection_profit', label='稽查清理盈利', amount=insp_profit, direction='income'))

    # --- 4. F类到账差额 ---
    fclass_q = select(func.coalesce(func.sum(PolicyRequestItem.arrival_amount - PolicyRequestItem.actual_cost), 0)).join(
        PolicyRequest, PolicyRequest.id == PolicyRequestItem.policy_request_id
    ).where(
        PolicyRequest.request_source == 'f_class',
        PolicyRequestItem.arrival_amount > 0,
        PolicyRequest.created_at.between(d_from, d_to),
    )
    if brand_id:
        fclass_q = fclass_q.where(PolicyRequest.brand_id == brand_id)
    fclass_diff = float((await db.execute(fclass_q)).scalar_one())
    items.append(ProfitItem(category='fclass_diff', label='F类到账差额', amount=fclass_diff, direction='income' if fclass_diff >= 0 else 'expense'))

    # --- 5. 回款返利（手动录入，暂时0）---
    items.append(ProfitItem(category='rebate', label='回款返利', amount=0, direction='income'))

    # --- 6. 报销费用 ---
    expense_q = select(func.coalesce(func.sum(Expense.amount), 0)).where(
        Expense.status == 'paid', Expense.created_at.between(d_from, d_to)
    )
    if brand_id:
        expense_q = expense_q.where(Expense.brand_id == brand_id)
    expense_total = float((await db.execute(expense_q)).scalar_one())
    items.append(ProfitItem(category='expense', label='报销费用', amount=expense_total, direction='expense'))

    # --- 7. 政策兑付亏损 ---
    policy_loss_q = select(func.coalesce(func.sum(func.abs(PolicyRequestItem.profit_loss)), 0)).join(
        PolicyRequest, PolicyRequest.id == PolicyRequestItem.policy_request_id
    ).where(PolicyRequestItem.profit_loss < 0, PolicyRequest.created_at.between(d_from, d_to))
    if brand_id:
        policy_loss_q = policy_loss_q.where(PolicyRequest.brand_id == brand_id)
    policy_loss = float((await db.execute(policy_loss_q)).scalar_one())
    items.append(ProfitItem(category='policy_loss', label='政策兑付亏损', amount=policy_loss, direction='expense'))

    # --- 8. 稽查外流亏损（只算已执行的案件，按执行时间过滤）---
    insp_loss_q = select(func.coalesce(func.sum(func.abs(InspectionCase.profit_loss)), 0)).where(
        InspectionCase.profit_loss < 0,
        InspectionCase.status.in_(('executed', 'closed')),
        InspectionCase.closed_at.between(d_from, d_to),
    )
    if brand_id:
        insp_loss_q = insp_loss_q.where(InspectionCase.brand_id == brand_id)
    insp_loss = float((await db.execute(insp_loss_q)).scalar_one())
    items.append(ProfitItem(category='inspection_loss', label='稽查外流亏损', amount=insp_loss, direction='expense'))

    # --- 9. 融资利息 ---
    try:
        from app.models.financing import FinancingOrder, FinancingRepayment
        interest_q = select(func.coalesce(func.sum(FinancingRepayment.interest_amount), 0)).join(
            FinancingOrder, FinancingOrder.id == FinancingRepayment.financing_order_id
        ).where(
            FinancingRepayment.status == 'approved',
            FinancingRepayment.created_at.between(d_from, d_to),
        )
        if brand_id:
            interest_q = interest_q.where(FinancingOrder.brand_id == brand_id)
        interest = float((await db.execute(interest_q)).scalar_one())
    except Exception:
        interest = 0
    items.append(ProfitItem(category='interest', label='融资利息', amount=interest, direction='expense'))

    # --- 10. 分货差价 ---
    # 分货本身没有利润/亏损，只是回款调整，暂记0
    items.append(ProfitItem(category='share_diff', label='分货差价', amount=0, direction='expense'))

    # --- 10.5 商城（mall）销售利润 + 10.6 商城坏账 ---
    # mall 独立记账：order.completed_at / partial_closed 在窗口内的，按 item.brand 切分收入
    # 毛利 = 按比例切分的 received_amount − cost_price_snapshot × qty − commission − bad_debt
    # bad_debt 单独列一行方便老板看"损失多少"（total_profit 里已扣过）
    try:
        from app.services.mall.profit_service import aggregate_mall_profit
        mall_agg = await aggregate_mall_profit(
            db, date_from=d_from, date_to=d_to, brand_id=brand_id,
        )
        mall_profit = float(mall_agg.get("total_profit") or 0)
        mall_bad_debt = float(mall_agg.get("total_bad_debt") or 0)
        items.append(ProfitItem(
            category='mall_sales',
            label='商城销售利润',
            amount=abs(mall_profit),
            direction='income' if mall_profit >= 0 else 'expense',
        ))
        if mall_bad_debt > 0:
            items.append(ProfitItem(
                category='mall_bad_debt',
                label='商城坏账（60 天未收款）',
                amount=mall_bad_debt,
                direction='expense',
            ))
    except Exception as _e:
        # 不影响主报表：mall 模块未初始化也能正常查 ERP 其他科目
        items.append(ProfitItem(category='mall_sales', label='商城销售利润', amount=0, direction='income'))

    # --- 11. 人力成本净额（主属该品牌员工工资 + 公司社保 + 提成 - 实际厂家补贴回款） ---
    try:
        from app.models.payroll import SalaryRecord, EmployeeBrandPosition, ManufacturerSalarySubsidy
        from app.models.user import Employee
        # 主属该品牌的员工 id 集合（不筛品牌时=全部员工）
        emp_filter = select(EmployeeBrandPosition.employee_id).where(EmployeeBrandPosition.is_primary == True)
        if brand_id:
            emp_filter = emp_filter.where(EmployeeBrandPosition.brand_id == brand_id)
        salary_q = select(func.coalesce(func.sum(
            SalaryRecord.actual_pay + SalaryRecord.social_security  # 实发 + 代扣的个人社保 = 员工应得，加上公司社保才是公司总支出
        ), 0)).where(
            SalaryRecord.status == 'paid',
            SalaryRecord.paid_at.between(d_from, d_to),
            SalaryRecord.employee_id.in_(emp_filter),
        )
        salary_cost = float((await db.execute(salary_q)).scalar_one())
        # 公司代缴社保（期间内发放过工资的员工）
        company_ss_q = select(func.coalesce(func.sum(Employee.company_social_security), 0)).where(
            Employee.id.in_(
                select(SalaryRecord.employee_id).where(
                    SalaryRecord.status == 'paid',
                    SalaryRecord.paid_at.between(d_from, d_to),
                    SalaryRecord.employee_id.in_(emp_filter),
                )
            )
        )
        company_ss = float((await db.execute(company_ss_q)).scalar_one())
        # 厂家补贴实际回款（按销售品牌而非主属品牌，减的是本品牌的补贴，即便员工是别的品牌主属）
        subsidy_q = select(func.coalesce(func.sum(ManufacturerSalarySubsidy.subsidy_amount), 0)).where(
            ManufacturerSalarySubsidy.status == 'reimbursed',
            ManufacturerSalarySubsidy.reimbursed_at.between(d_from, d_to),
        )
        if brand_id:
            subsidy_q = subsidy_q.where(ManufacturerSalarySubsidy.brand_id == brand_id)
        subsidy_income = float((await db.execute(subsidy_q)).scalar_one())
        net_hr_cost = salary_cost + company_ss - subsidy_income
    except Exception:
        net_hr_cost = 0
    items.append(ProfitItem(category='hr_cost', label='人力成本净额', amount=net_hr_cost, direction='expense'))

    total_income = sum(i.amount for i in items if i.direction == 'income')
    total_expense = sum(i.amount for i in items if i.direction == 'expense')

    return ProfitSummaryResponse(
        total_income=total_income,
        total_expense=total_expense,
        net_profit=total_income - total_expense,
        items=items,
    )


@router.get("/profit-detail")
async def profit_detail(
    user: CurrentUser,
    category: str = Query(...),
    brand_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return detail records for a specific profit category."""
    d_from = datetime.strptime(date_from, '%Y-%m-%d') if date_from else datetime(2020, 1, 1)
    d_to = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59) if date_to else datetime(2099, 12, 31)
    results = []

    if category == 'sales':
        stmt = select(Order).where(Order.created_at.between(d_from, d_to), Order.status != 'pending')
        if brand_id:
            stmt = stmt.where(Order.brand_id == brand_id)
        stmt = stmt.order_by(Order.created_at.desc()).limit(100)
        rows = (await db.execute(stmt)).scalars().all()
        for o in rows:
            revenue = sum(float(oi.unit_price) * oi.quantity for oi in o.items)
            cost = 0
            for oi in o.items:
                allocs = (await db.execute(select(StockOutAllocation).where(StockOutAllocation.order_item_id == oi.id))).scalars().all()
                cost += sum(float(a.allocated_cost_price) * a.allocated_quantity for a in allocs)
            gross = revenue - cost

            # 政策盈亏
            policy_pl = 0
            prs = (await db.execute(select(PolicyRequest).where(PolicyRequest.order_id == o.id))).scalars().all()
            for pr in prs:
                for ri in pr.request_items:
                    policy_pl += float(ri.profit_loss or 0)

            # 稽查盈亏
            insp_pl = 0
            cases = (await db.execute(select(InspectionCase).where(InspectionCase.original_order_id == o.id))).scalars().all()
            for c in cases:
                insp_pl += float(c.profit_loss or 0)

            total = gross + policy_pl + insp_pl
            parts = []
            if revenue: parts.append(f"销售收入¥{revenue:,.0f}")
            if cost: parts.append(f"成本¥{cost:,.0f}")
            if gross != 0: parts.append(f"毛利¥{gross:,.0f}")
            if policy_pl != 0: parts.append(f"政策{'盈' if policy_pl > 0 else '亏'}¥{abs(policy_pl):,.0f}")
            if insp_pl != 0: parts.append(f"稽查{'盈' if insp_pl > 0 else '亏'}¥{abs(insp_pl):,.0f}")

            cust = o.customer.name if o.customer else '-'
            results.append({
                "id": o.id, "label": o.order_no,
                "detail": f"客户:{cust} | {' | '.join(parts)}",
                "amount": total, "time": str(o.created_at)[:16],
            })

    elif category in ('policy_profit', 'policy_loss'):
        is_profit = category == 'policy_profit'
        stmt = select(PolicyRequestItem).join(PolicyRequest).where(
            PolicyRequestItem.profit_loss > 0 if is_profit else PolicyRequestItem.profit_loss < 0,
            PolicyRequest.created_at.between(d_from, d_to),
        )
        if brand_id:
            stmt = stmt.where(PolicyRequest.brand_id == brand_id)
        stmt = stmt.order_by(PolicyRequest.created_at.desc()).limit(100)
        rows = (await db.execute(stmt)).scalars().all()
        benefit_labels = {'tasting_meal': '品鉴会餐费', 'tasting_wine': '品鉴酒', 'travel': '庄园之旅', 'rebate': '返利', 'gift': '赠品', 'other': '其他'}
        for ri in rows:
            name = ri.name or benefit_labels.get(ri.benefit_type, ri.benefit_type)
            # 拿关联的订单号
            pr = await db.get(PolicyRequest, ri.policy_request_id)
            order_no = ''
            if pr and pr.order_id:
                o = await db.get(Order, pr.order_id)
                order_no = o.order_no if o else ''
            label = name if name and name != '1' else (order_no or ri.id[:12])
            detail_parts = [benefit_labels.get(ri.benefit_type, ri.benefit_type)]
            if ri.scheme_no: detail_parts.append(f"方案号:{ri.scheme_no}")
            if order_no: detail_parts.append(f"订单:{order_no}")
            detail_parts.append(f"面值¥{ri.standard_total} | 承诺¥{ri.total_value} | 花费¥{ri.actual_cost}")
            results.append({"id": ri.id, "label": label, "detail": ' | '.join(detail_parts), "amount": float(ri.profit_loss), "time": str(ri.created_at)[:16]})

    elif category in ('inspection_profit', 'inspection_loss'):
        is_profit = category == 'inspection_profit'
        stmt = select(InspectionCase).where(
            InspectionCase.profit_loss > 0 if is_profit else InspectionCase.profit_loss < 0,
            InspectionCase.created_at.between(d_from, d_to),
        )
        if brand_id:
            stmt = stmt.where(InspectionCase.brand_id == brand_id)
        stmt = stmt.order_by(InspectionCase.created_at.desc()).limit(100)
        rows = (await db.execute(stmt)).scalars().all()
        type_labels = {'outflow_malicious': 'A1恶意→备用库', 'outflow_nonmalicious': 'A2非恶意→主仓', 'outflow_transfer': 'A3被转码', 'inflow_resell': 'B1加价回售', 'inflow_transfer': 'B2转码入库'}
        for c in rows:
            label = type_labels.get(c.case_type, c.case_type)
            product_name = c.product.name if c.product else '-'
            detail_parts = [f"商品:{product_name}", f"{c.quantity}{c.quantity_unit}"]
            if c.counterparty: detail_parts.append(f"对方:{c.counterparty}")
            if c.purchase_price: detail_parts.append(f"回收/买入¥{c.purchase_price}/瓶")
            if c.penalty_amount: detail_parts.append(f"罚款¥{c.penalty_amount}")
            if c.reward_amount: detail_parts.append(f"奖励¥{c.reward_amount}")
            results.append({"id": c.id, "label": label, "detail": ' | '.join(detail_parts), "amount": float(c.profit_loss), "time": str(c.created_at)[:16]})

    elif category == 'fclass_diff':
        stmt = select(PolicyRequestItem).join(PolicyRequest).where(
            PolicyRequest.request_source == 'f_class',
            PolicyRequestItem.arrival_amount > 0,
            PolicyRequest.created_at.between(d_from, d_to),
        )
        if brand_id:
            stmt = stmt.where(PolicyRequest.brand_id == brand_id)
        rows = (await db.execute(stmt)).scalars().all()
        for ri in rows:
            diff = float(ri.arrival_amount) - float(ri.actual_cost)
            pr = await db.get(PolicyRequest, ri.policy_request_id)
            label = ri.name or (pr.usage_purpose if pr else '') or ri.id[:12]
            results.append({"id": ri.id, "label": label, "detail": f"到账¥{ri.arrival_amount} | 花费¥{ri.actual_cost} | 差额¥{diff:,.0f}", "amount": diff, "time": str(ri.created_at)[:16]})

    elif category == 'expense':
        stmt = select(Expense).where(Expense.status == 'paid', Expense.created_at.between(d_from, d_to))
        if brand_id:
            stmt = stmt.where(Expense.brand_id == brand_id)
        stmt = stmt.order_by(Expense.created_at.desc()).limit(100)
        rows = (await db.execute(stmt)).scalars().all()
        for e in rows:
            label = e.description or e.expense_no
            applicant = e.applicant.name if e.applicant else '-'
            results.append({"id": e.id, "label": label, "detail": f"编号:{e.expense_no} | 申请人:{applicant}", "amount": float(e.amount), "time": str(e.created_at)[:16]})

    elif category == 'interest':
        try:
            from app.models.financing import FinancingOrder, FinancingRepayment
            stmt = select(FinancingRepayment).join(FinancingOrder).where(
                FinancingRepayment.status == 'approved', FinancingRepayment.created_at.between(d_from, d_to),
            )
            if brand_id:
                stmt = stmt.where(FinancingOrder.brand_id == brand_id)
            rows = (await db.execute(stmt)).scalars().all()
            for r in rows:
                rtype = '退仓' if r.repayment_type == 'return_warehouse' else '还款'
                label = f"融资{rtype}"
                results.append({"id": r.id, "label": label, "detail": f"编号:{r.repayment_no} | 本金¥{r.principal_amount} | {r.interest_days}天 | 利息¥{r.interest_amount}", "amount": float(r.interest_amount), "time": str(r.created_at)[:16]})
        except Exception:
            pass

    return results

@router.get("/trend")
async def dashboard_trend(
    user: CurrentUser,
    brand_id: Optional[str] = Query(None),
    days: int = Query(30, ge=7, le=90),
    db: AsyncSession = Depends(get_db),
):
    """近 N 天销售/回款日趋势 + 本月分品牌汇总"""
    from sqlalchemy import cast, Date as _SqlDate
    from datetime import date as _date, timedelta as _td
    from app.models.finance import Receipt as _Receipt

    end = _date.today()
    start = end - _td(days=days - 1)

    # 每日销售额（排除已驳回/取消）
    sales_stmt = (
        select(cast(Order.created_at, _SqlDate).label("d"),
               func.coalesce(func.sum(Order.total_amount), 0).label("v"))
        .where(
            cast(Order.created_at, _SqlDate) >= start,
            Order.status.notin_(["rejected", "cancelled"]),
        )
    )
    if brand_id:
        sales_stmt = sales_stmt.where(Order.brand_id == brand_id)
    sales_stmt = sales_stmt.group_by("d").order_by("d")
    sales_rows = (await db.execute(sales_stmt)).all()
    sales_map = {str(r.d): float(r.v or 0) for r in sales_rows}

    # 每日回款额
    recv_stmt = (
        select(_Receipt.receipt_date.label("d"),
               func.coalesce(func.sum(_Receipt.amount), 0).label("v"))
        .select_from(_Receipt)
        .join(Order, Order.id == _Receipt.order_id, isouter=True)
        .where(_Receipt.receipt_date >= start)
    )
    if brand_id:
        recv_stmt = recv_stmt.where(Order.brand_id == brand_id)
    recv_stmt = recv_stmt.group_by(_Receipt.receipt_date).order_by(_Receipt.receipt_date)
    recv_rows = (await db.execute(recv_stmt)).all()
    recv_map = {str(r.d): float(r.v or 0) for r in recv_rows}

    trend = []
    d = start
    while d <= end:
        key = str(d)
        trend.append({
            "date": key,
            "sales": sales_map.get(key, 0),
            "receipt": recv_map.get(key, 0),
        })
        d += _td(days=1)

    # 本月分品牌销售（排除已驳回/取消）
    now_first = _date(end.year, end.month, 1)
    brand_sales_stmt = (
        select(Order.brand_id,
               func.coalesce(func.sum(Order.total_amount), 0).label("v"))
        .where(
            cast(Order.created_at, _SqlDate) >= now_first,
            Order.status.notin_(["rejected", "cancelled"]),
        )
        .group_by(Order.brand_id)
    )
    brand_rows = (await db.execute(brand_sales_stmt)).all()
    brand_stat = []
    for r in brand_rows:
        bid = r.brand_id
        if bid:
            b = await db.get(Brand, bid)
            brand_stat.append({"brand_id": bid, "brand_name": b.name if b else bid[:8], "sales": float(r.v or 0)})
        else:
            brand_stat.append({"brand_id": None, "brand_name": "其他", "sales": float(r.v or 0)})

    # 订单状态分布（最近 30 天）
    status_stmt = (
        select(Order.status, func.count(Order.id).label("c"))
        .where(cast(Order.created_at, _SqlDate) >= start)
        .group_by(Order.status)
    )
    if brand_id:
        status_stmt = status_stmt.where(Order.brand_id == brand_id)
    status_rows = (await db.execute(status_stmt)).all()
    order_status = [{"status": r.status, "count": int(r.c or 0)} for r in status_rows]

    return {
        "trend": trend,
        "brand_sales": brand_stat,
        "order_status": order_status,
    }


# =============================================================================
# Boss 视角：经营单元看板
# =============================================================================


@router.get("/business-unit-summary")
async def business_unit_summary(
    user: CurrentUser,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """老板视角：按经营单元（品牌代理/零售/批发商城）聚合 GMV / 利润 / 库存 / 账户 / 待收。

    权限：admin / boss
    时间窗：默认本月 1 号 → 今天，两头闭闭。
    """
    from app.core.permissions import require_role
    from app.models.org_unit import OrgUnit
    from app.models.order import Order as _Order
    from app.models.mall.order import MallOrder as _MallOrder
    from app.models.mall.inventory import MallInventory as _MallInv
    from app.models.inventory import Inventory as _Inv
    from app.models.product import Warehouse as _Warehouse, Account as _Acc
    from app.services.mall.profit_service import aggregate_mall_profit
    from app.services.store_sale_service import aggregate_retail_profit

    require_role(user, "admin", "boss")

    # 时间窗规整
    today = date.today()
    if date_from is None:
        date_from = today.replace(day=1)
    if date_to is None:
        date_to = today

    window_from = datetime(date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc)
    # date_to 闭区间 → +1 天
    from datetime import timedelta as _td
    window_to = datetime(
        (date_to + _td(days=1)).year,
        (date_to + _td(days=1)).month,
        (date_to + _td(days=1)).day,
        tzinfo=timezone.utc,
    )

    # 1. 取 active org_units
    units = (await db.execute(
        select(OrgUnit).where(OrgUnit.is_active.is_(True))
        .order_by(OrgUnit.sort_order, OrgUnit.created_at)
    )).scalars().all()

    results = []
    grand = {
        "gmv": Decimal("0"),
        "net_profit": Decimal("0"),
        "commission_total": Decimal("0"),
        "inventory_value": Decimal("0"),
        "account_balance": Decimal("0"),
        "pending_receivables": Decimal("0"),
    }

    for ou in units:
        gmv = Decimal("0")
        net_profit = Decimal("0")
        commission_total = Decimal("0")
        inventory_value = Decimal("0")
        account_balance = Decimal("0")
        pending_receivables = Decimal("0")

        if ou.code == "brand_agent":
            # GMV：B2B orders.total_amount
            row = (await db.execute(
                select(
                    func.coalesce(func.sum(_Order.total_amount), 0).label("gmv"),
                ).where(_Order.org_unit_id == ou.id)
                .where(_Order.created_at >= window_from)
                .where(_Order.created_at < window_to)
                .where(_Order.status.notin_(["rejected", "cancelled"]))
            )).one()
            gmv = Decimal(str(row.gmv or 0))

            # 提成
            from app.models.user import Commission as _Comm
            c_row = (await db.execute(
                select(func.coalesce(func.sum(_Comm.commission_amount), 0))
                .where(_Comm.org_unit_id == ou.id)
                .where(_Comm.created_at >= window_from)
                .where(_Comm.created_at < window_to)
            )).scalar()
            commission_total = Decimal(str(c_row or 0))

            # 利润（简化版本：gmv - 提成；详细利润走 /profit-summary 端点）
            net_profit = gmv - commission_total

            # 库存价值：品牌主仓 / backup / tasting
            inv_row = (await db.execute(
                select(
                    func.coalesce(
                        func.sum(_Inv.quantity * _Inv.cost_price), 0
                    )
                ).join(_Warehouse, _Warehouse.id == _Inv.warehouse_id)
                .where(_Warehouse.warehouse_type.in_(["main", "backup", "tasting"]))
            )).scalar()
            inventory_value = Decimal(str(inv_row or 0))

            # 账户余额：level='project'
            acc_row = (await db.execute(
                select(func.coalesce(func.sum(_Acc.balance), 0))
                .where(_Acc.level == "project")
                .where(_Acc.is_active.is_(True))
            )).scalar()
            account_balance = Decimal(str(acc_row or 0))

            # 待收：partial_closed 订单的未收部分
            pr_row = (await db.execute(
                select(
                    func.coalesce(
                        func.sum(_Order.total_amount - func.coalesce(_Order.customer_paid_amount, 0)),
                        0,
                    )
                ).where(_Order.org_unit_id == ou.id)
                .where(_Order.status == "partial_closed")
            )).scalar()
            pending_receivables = Decimal(str(pr_row or 0))

        elif ou.code == "retail":
            # 零售
            r_data = await aggregate_retail_profit(
                db, date_from=window_from, date_to=window_to
            )
            gmv = Decimal(r_data["total_revenue"])
            commission_total = Decimal(r_data["total_commission"])
            net_profit = Decimal(r_data["total_profit"])

            # 库存（warehouse_type='store' 门店仓）
            inv_row = (await db.execute(
                select(
                    func.coalesce(
                        func.sum(_Inv.quantity * _Inv.cost_price), 0
                    )
                ).join(_Warehouse, _Warehouse.id == _Inv.warehouse_id)
                .where(_Warehouse.warehouse_type == "store")
            )).scalar()
            inventory_value = Decimal(str(inv_row or 0))

            # STORE_MASTER 账户
            acc = (await db.execute(
                select(_Acc).where(_Acc.code == "STORE_MASTER")
            )).scalar_one_or_none()
            account_balance = Decimal(str(acc.balance)) if acc else Decimal("0")

            pending_receivables = Decimal("0")  # 门店当场结清

        elif ou.code == "mall":
            m_data = await aggregate_mall_profit(
                db, date_from=window_from, date_to=window_to
            )
            gmv = Decimal(m_data["total_revenue"])
            commission_total = Decimal(m_data["total_commission"])
            net_profit = Decimal(m_data["total_profit"])

            # mall_inventory × avg_cost_price
            inv_row = (await db.execute(
                select(
                    func.coalesce(
                        func.sum(_MallInv.quantity * _MallInv.avg_cost_price), 0
                    )
                )
            )).scalar()
            inventory_value = Decimal(str(inv_row or 0))

            # MALL_MASTER 账户
            acc = (await db.execute(
                select(_Acc).where(_Acc.code == "MALL_MASTER")
            )).scalar_one_or_none()
            account_balance = Decimal(str(acc.balance)) if acc else Decimal("0")

            # 待收：partial_closed mall_orders
            pr_row = (await db.execute(
                select(
                    func.coalesce(
                        func.sum(_MallOrder.pay_amount - func.coalesce(_MallOrder.received_amount, 0)),
                        0,
                    )
                ).where(_MallOrder.org_unit_id == ou.id)
                .where(_MallOrder.status == "partial_closed")
            )).scalar()
            pending_receivables = Decimal(str(pr_row or 0))

        # 未来新单元（code 不是内置 3 个）：暂时全 0，等用户接入对应逻辑
        else:
            pass

        results.append({
            "id": ou.id,
            "code": ou.code,
            "name": ou.name,
            "gmv": float(gmv),
            "net_profit": float(net_profit),
            "commission_total": float(commission_total),
            "inventory_value": float(inventory_value),
            "account_balance": float(account_balance),
            "pending_receivables": float(pending_receivables),
        })
        grand["gmv"] += gmv
        grand["net_profit"] += net_profit
        grand["commission_total"] += commission_total
        grand["inventory_value"] += inventory_value
        grand["account_balance"] += account_balance
        grand["pending_receivables"] += pending_receivables

    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "units": results,
        "grand_total": {k: float(v) for k, v in grand.items()},
    }
