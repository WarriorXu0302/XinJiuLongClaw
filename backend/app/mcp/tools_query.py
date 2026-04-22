"""
MCP 查询类工具 — 只读，安全。
"""
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.mcp.auth import require_mcp_employee, require_mcp_role
from app.mcp.deps import get_mcp_db
from app.models.order import Order, OrderItem
from app.models.customer import Customer
from app.models.inventory import Inventory
from app.models.payroll import SalaryRecord, ManufacturerSalarySubsidy
from app.models.sales_target import SalesTarget
from app.models.inspection import InspectionCase
from app.models.finance import Receipt
from app.models.product import Account

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# 1. 订单查询
# ═══════════════════════════════════════════════════════════════════

class QueryOrdersRequest(BaseModel):
    brand_id: Optional[str] = None
    status: Optional[str] = None
    payment_status: Optional[str] = None
    keyword: Optional[str] = None
    limit: int = 20

@router.post("/query-orders")
async def query_orders(body: QueryOrdersRequest, db: AsyncSession = Depends(get_mcp_db)):
    """查询订单列表。支持按品牌/状态/付款状态/关键字过滤。"""
    require_mcp_employee(db.info.get("mcp_user", {}))
    brand_id, status, payment_status, keyword, limit = body.brand_id, body.status, body.payment_status, body.keyword, body.limit
    stmt = select(Order).options(
        selectinload(Order.customer), selectinload(Order.salesman),
        selectinload(Order.items).selectinload(OrderItem.product),
    )
    if brand_id:
        stmt = stmt.where(Order.brand_id == brand_id)
    if status:
        stmt = stmt.where(Order.status == status)
    if payment_status:
        stmt = stmt.where(Order.payment_status == payment_status)
    if keyword:
        stmt = stmt.where(Order.order_no.ilike(f"%{keyword}%"))
    stmt = stmt.order_by(Order.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [{
        "order_no": o.order_no, "customer": o.customer.name if o.customer else None,
        "salesman": o.salesman.name if o.salesman else None,
        "total_amount": float(o.total_amount), "deal_amount": float(o.deal_amount or 0),
        "customer_paid_amount": float(o.customer_paid_amount or 0),
        "settlement_mode": o.settlement_mode, "status": o.status,
        "payment_status": o.payment_status,
        "items": [{"product": it.product.name if it.product else None, "qty": it.quantity, "unit": it.quantity_unit, "price": float(it.unit_price)} for it in (o.items or [])],
    } for o in rows]


class OrderDetailRequest(BaseModel):
    order_no: str

@router.post("/query-order-detail")
async def query_order_detail(body: OrderDetailRequest, db: AsyncSession = Depends(get_mcp_db)):
    """查询单个订单详情（含收款记录）。"""
    require_mcp_employee(db.info.get("mcp_user", {}))
    order_no = body.order_no
    o = (await db.execute(
        select(Order).where(Order.order_no == order_no)
        .options(selectinload(Order.customer), selectinload(Order.salesman),
                 selectinload(Order.items).selectinload(OrderItem.product))
    )).scalar_one_or_none()
    if not o:
        return {"error": f"订单 {order_no} 不存在"}
    receipts = (await db.execute(
        select(Receipt).where(Receipt.order_id == o.id).order_by(Receipt.created_at)
    )).scalars().all()
    return {
        "order_no": o.order_no, "customer": o.customer.name if o.customer else None,
        "total_amount": float(o.total_amount), "customer_paid_amount": float(o.customer_paid_amount or 0),
        "policy_gap": float(o.policy_gap or 0), "settlement_mode": o.settlement_mode,
        "status": o.status, "payment_status": o.payment_status,
        "receipts": [{"amount": float(r.amount), "source_type": r.source_type, "date": str(r.receipt_date)} for r in receipts],
    }


# ═══════════════════════════════════════════════════════════════════
# 2. 客户查询
# ═══════════════════════════════════════════════════════════════════

class QueryCustomersRequest(BaseModel):
    brand_id: Optional[str] = None
    keyword: Optional[str] = None
    limit: int = 20

@router.post("/query-customers")
async def query_customers(body: QueryCustomersRequest, db: AsyncSession = Depends(get_mcp_db)):
    """查询客户列表。"""
    require_mcp_employee(db.info.get("mcp_user", {}))
    brand_id, keyword, limit = body.brand_id, body.keyword, body.limit
    stmt = select(Customer)
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(Customer.name.ilike(kw) | Customer.contact_name.ilike(kw))
    stmt = stmt.order_by(Customer.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"code": c.code, "name": c.name, "contact": c.contact_name, "phone": getattr(c, 'contact_phone', None), "settlement": c.settlement_mode} for c in rows]


# ═══════════════════════════════════════════════════════════════════
# 3. 库存查询
# ═══════════════════════════════════════════════════════════════════

class QueryInventoryRequest(BaseModel):
    brand_id: Optional[str] = None
    product_keyword: Optional[str] = None
    low_stock_only: bool = False

@router.post("/query-inventory")
async def query_inventory(body: QueryInventoryRequest, db: AsyncSession = Depends(get_mcp_db)):
    """查询库存。可只看低库存预警。"""
    require_mcp_role(db.info.get("mcp_user", {}), "boss", "warehouse", "salesman", "sales_manager", "purchase", "finance")
    brand_id, low_stock_only = body.brand_id, body.low_stock_only
    from app.models.product import Product, Warehouse
    stmt = select(Inventory).options(
        selectinload(Inventory.product), selectinload(Inventory.warehouse),
    )
    if brand_id:
        stmt = stmt.join(Warehouse, Warehouse.id == Inventory.warehouse_id).where(Warehouse.brand_id == brand_id)
    stmt = stmt.where(Inventory.quantity > 0)
    rows = (await db.execute(stmt)).scalars().all()
    result = []
    for inv in rows:
        bpc = inv.product.bottles_per_case if inv.product else 1
        cases = inv.quantity / bpc if bpc else 0
        if low_stock_only and cases >= 10:
            continue
        result.append({
            "product": inv.product.name if inv.product else None,
            "warehouse": inv.warehouse.name if inv.warehouse else None,
            "quantity_bottles": inv.quantity, "cases": round(cases, 1),
            "cost_price": float(inv.cost_price or 0),
            "value": float((inv.cost_price or 0) * inv.quantity),
        })
    return result


# ═══════════════════════════════════════════════════════════════════
# 4. 利润台账
# ═══════════════════════════════════════════════════════════════════

class QueryProfitRequest(BaseModel):
    brand_id: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None

@router.post("/query-profit-summary")
async def query_profit_summary(body: QueryProfitRequest, db: AsyncSession = Depends(get_mcp_db)):
    """查询利润台账汇总（11 个科目）。"""
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance", "sales_manager")
    from app.api.routes.dashboard import profit_summary as _fn
    # 直接调内部函数（传 user + db + query 参数）
    return await _fn(user=user, brand_id=body.brand_id, date_from=body.date_from, date_to=body.date_to, db=db)


# ═══════════════════════════════════════════════════════════════════
# 5. 账户余额
# ═══════════════════════════════════════════════════════════════════

class QueryAccountsRequest(BaseModel):
    brand_id: Optional[str] = None

@router.post("/query-account-balances")
async def query_account_balances(body: QueryAccountsRequest, db: AsyncSession = Depends(get_mcp_db)):
    """查询账户余额。按品牌分组。"""
    require_mcp_role(db.info.get("mcp_user", {}), "boss", "finance")
    brand_id = body.brand_id
    stmt = select(Account).where(Account.is_active == True)
    if brand_id:
        from sqlalchemy import or_
        stmt = stmt.where(or_(Account.brand_id == brand_id, Account.level == 'master'))
    rows = (await db.execute(stmt)).scalars().all()
    return [{
        "name": a.name, "type": a.account_type, "level": a.level,
        "brand": a.brand.name if a.brand else "公司",
        "balance": float(a.balance),
    } for a in rows]


# ═══════════════════════════════════════════════════════════════════
# 6. 工资查询
# ═══════════════════════════════════════════════════════════════════

class QuerySalaryRequest(BaseModel):
    period: Optional[str] = None
    employee_name: Optional[str] = None

@router.post("/query-salary-records")
async def query_salary_records(body: QuerySalaryRequest, db: AsyncSession = Depends(get_mcp_db)):
    """查询工资单列表。"""
    require_mcp_role(db.info.get("mcp_user", {}), "boss", "finance")
    period, employee_name = body.period, body.employee_name
    from app.models.user import Employee
    stmt = select(SalaryRecord).options(selectinload(SalaryRecord.employee))
    if period:
        stmt = stmt.where(SalaryRecord.period == period)
    if employee_name:
        stmt = stmt.join(Employee, Employee.id == SalaryRecord.employee_id).where(Employee.name.ilike(f"%{employee_name}%"))
    stmt = stmt.order_by(SalaryRecord.period.desc()).limit(50)
    rows = (await db.execute(stmt)).scalars().all()
    return [{
        "employee": r.employee.name if r.employee else None, "period": r.period,
        "total_pay": float(r.total_pay), "actual_pay": float(r.actual_pay),
        "commission": float(r.commission_total), "status": r.status,
    } for r in rows]


# ═══════════════════════════════════════════════════════════════════
# 7. 销售目标
# ═══════════════════════════════════════════════════════════════════

class QueryTargetsRequest(BaseModel):
    target_year: int = 2026
    target_level: Optional[str] = None
    brand_id: Optional[str] = None

@router.post("/query-sales-targets")
async def query_sales_targets(body: QueryTargetsRequest, db: AsyncSession = Depends(get_mcp_db)):
    """查询销售目标及完成率。"""
    require_mcp_role(db.info.get("mcp_user", {}), "boss", "finance", "sales_manager", "salesman")
    target_year, target_level, brand_id = body.target_year, body.target_level, body.brand_id
    stmt = select(SalesTarget).where(SalesTarget.target_year == target_year, SalesTarget.status == 'approved')
    if target_level:
        stmt = stmt.where(SalesTarget.target_level == target_level)
    if brand_id:
        stmt = stmt.where(SalesTarget.brand_id == brand_id)
    stmt = stmt.options(selectinload(SalesTarget.brand), selectinload(SalesTarget.employee))
    rows = (await db.execute(stmt)).scalars().all()
    return [{
        "level": t.target_level, "month": t.target_month,
        "brand": t.brand.name if t.brand else None,
        "employee": t.employee.name if t.employee else None,
        "sales_target": float(t.sales_target), "receipt_target": float(t.receipt_target),
    } for t in rows]


# ═══════════════════════════════════════════════════════════════════
# 8. 稽查案件查询
# ═══════════════════════════════════════════════════════════════════

class QueryInspectionRequest(BaseModel):
    brand_id: Optional[str] = None
    status: Optional[str] = None
    limit: int = 20

@router.post("/query-inspection-cases")
async def query_inspection_cases(body: QueryInspectionRequest, db: AsyncSession = Depends(get_mcp_db)):
    """查询稽查案件列表。"""
    require_mcp_role(db.info.get("mcp_user", {}), "boss", "finance")
    brand_id, status, limit = body.brand_id, body.status, body.limit
    stmt = select(InspectionCase)
    if brand_id:
        stmt = stmt.where(InspectionCase.brand_id == brand_id)
    if status:
        stmt = stmt.where(InspectionCase.status == status)
    stmt = stmt.order_by(InspectionCase.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [{
        "case_no": c.case_no, "type": c.case_type, "direction": c.direction,
        "quantity": c.quantity, "unit": c.quantity_unit,
        "profit_loss": float(c.profit_loss), "status": c.status,
    } for c in rows]


# ═══════════════════════════════════════════════════════════════════
# 9. 厂家补贴查询
# ═══════════════════════════════════════════════════════════════════

class QuerySubsidiesRequest(BaseModel):
    brand_id: Optional[str] = None
    period: Optional[str] = None
    status: Optional[str] = None

@router.post("/query-manufacturer-subsidies")
async def query_manufacturer_subsidies(body: QuerySubsidiesRequest, db: AsyncSession = Depends(get_mcp_db)):
    """查询厂家工资补贴应收。"""
    require_mcp_role(db.info.get("mcp_user", {}), "boss", "finance")
    brand_id, period, status = body.brand_id, body.period, body.status
    stmt = select(ManufacturerSalarySubsidy).options(
        selectinload(ManufacturerSalarySubsidy.employee),
        selectinload(ManufacturerSalarySubsidy.brand),
    )
    if brand_id:
        stmt = stmt.where(ManufacturerSalarySubsidy.brand_id == brand_id)
    if period:
        stmt = stmt.where(ManufacturerSalarySubsidy.period == period)
    if status:
        stmt = stmt.where(ManufacturerSalarySubsidy.status == status)
    stmt = stmt.order_by(ManufacturerSalarySubsidy.created_at.desc()).limit(50)
    rows = (await db.execute(stmt)).scalars().all()
    return [{
        "employee": s.employee.name if s.employee else None,
        "brand": s.brand.name if s.brand else None,
        "period": s.period, "amount": float(s.subsidy_amount), "status": s.status,
    } for s in rows]


# ═══════════════════════════════════════════════════════════════════
# 10. 考勤汇总
# ═══════════════════════════════════════════════════════════════════

class QueryAttendanceRequest(BaseModel):
    period: str = "2026-04"

@router.post("/query-attendance-summary")
async def query_attendance_summary(body: QueryAttendanceRequest, db: AsyncSession = Depends(get_mcp_db)):
    """查询某月考勤汇总。"""
    require_mcp_role(db.info.get("mcp_user", {}), "boss", "finance")
    period = body.period
    from app.models.attendance import CheckinRecord, LeaveRequest
    from app.models.user import Employee
    from datetime import date, timedelta
    y, m = map(int, period.split("-"))
    start = date(y, m, 1)
    end = date(y + 1, 1, 1) - timedelta(days=1) if m == 12 else date(y, m + 1, 1) - timedelta(days=1)

    emps = (await db.execute(select(Employee).where(Employee.status == 'active'))).scalars().all()
    result = []
    for emp in emps:
        checkins = (await db.execute(
            select(CheckinRecord).where(CheckinRecord.employee_id == emp.id, CheckinRecord.checkin_date.between(start, end))
        )).scalars().all()
        late = sum(1 for c in checkins if c.status == 'late')
        late30 = sum(1 for c in checkins if c.status == 'late_over30')
        days = len({c.checkin_date for c in checkins if c.checkin_type == 'work_in'})
        leaves = (await db.execute(
            select(LeaveRequest).where(LeaveRequest.employee_id == emp.id, LeaveRequest.status == 'approved',
                                       LeaveRequest.start_date <= end, LeaveRequest.end_date >= start)
        )).scalars().all()
        leave_days = sum(float(l.total_days or 0) for l in leaves if l.leave_type != 'overtime_off')
        result.append({
            "employee": emp.name, "work_days": days,
            "late": late, "late_over30": late30, "leave_days": leave_days,
            "full_attendance": late == 0 and late30 == 0 and leave_days == 0,
        })
    return result


# ═══════════════════════════════════════════════════════════════════
# 12. 查询政策模板
# ═══════════════════════════════════════════════════════════════════

class QueryPolicyTemplatesRequest(BaseModel):
    brand_id: Optional[str] = None
    keyword: Optional[str] = None

@router.post("/query-policy-templates")
async def query_policy_templates(body: QueryPolicyTemplatesRequest, db: AsyncSession = Depends(get_mcp_db)):
    """查询政策模板列表（含 ID、指导价、客户到手价、最小箱数）。建单时需要 policy_template_id。"""
    from app.models.policy_template import PolicyTemplate
    stmt = select(PolicyTemplate).where(PolicyTemplate.is_active == True)
    if body.brand_id:
        stmt = stmt.where(PolicyTemplate.brand_id == body.brand_id)
    if body.keyword:
        stmt = stmt.where(PolicyTemplate.name.ilike(f"%{body.keyword}%"))
    stmt = stmt.order_by(PolicyTemplate.created_at.desc()).limit(50)
    rows = (await db.execute(stmt)).scalars().all()
    return [{
        "id": t.id, "code": t.code, "name": t.name,
        "brand_id": t.brand_id,
        "required_unit_price": float(t.required_unit_price or 0),
        "customer_unit_price": float(t.customer_unit_price or 0),
        "min_cases": t.min_cases, "total_policy_value": float(t.total_policy_value or 0),
    } for t in rows]


# ═══════════════════════════════════════════════════════════════════
# 13. 查询品牌列表
# ═══════════════════════════════════════════════════════════════════

@router.post("/query-brands")
async def query_brands(db: AsyncSession = Depends(get_mcp_db)):
    """查询所有品牌（含 ID）。建单/建客户/绑岗位时需要 brand_id。"""
    from app.models.product import Brand
    rows = (await db.execute(select(Brand).order_by(Brand.code))).scalars().all()
    return [{"id": b.id, "code": b.code, "name": b.name} for b in rows]


# ═══════════════════════════════════════════════════════════════════
# 14. 查询岗位字典
# ═══════════════════════════════════════════════════════════════════

@router.post("/query-positions")
async def query_positions(db: AsyncSession = Depends(get_mcp_db)):
    """查询岗位代码列表。绑定员工品牌岗位时需要 position_code。"""
    from app.models.payroll import Position
    rows = (await db.execute(select(Position).where(Position.is_active == True).order_by(Position.sort_order))).scalars().all()
    return [{"code": p.code, "name": p.name} for p in rows]
