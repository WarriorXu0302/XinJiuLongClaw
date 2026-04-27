"""
员工月度绩效档案 — 聚合销售目标/考勤/佣金/KPI
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, extract
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_role
from app.core.security import CurrentUser
from app.models.user import Employee
from app.models.sales_target import SalesTarget
from app.models.attendance import CheckinRecord, CustomerVisit, LeaveRequest
from app.models.payroll import SalaryRecord, AssessmentItem, EmployeeBrandPosition, SalaryOrderLink
from app.models.order import Order
from app.models.finance import Receipt
from app.models.product import Brand

router = APIRouter()


@router.get("/employee-monthly")
async def employee_monthly(
    user: CurrentUser,
    period: str = Query(..., description="YYYY-MM"),
    employee_id: Optional[str] = Query(None, description="不传=所有员工"),
    db: AsyncSession = Depends(get_db),
):
    """
    员工月度绩效档案：
      - 基本信息（姓名/部门/品牌岗位）
      - 销售：目标/实际/完成率（按月）
      - 回款：目标/实际/完成率
      - 考勤：出勤/迟到/旷工/请假/有效拜访
      - 佣金：本月工资单的 commission_total + manager_share_total
      - KPI：本月所有 AssessmentItem 完成率
    """
    y, m = map(int, period.split("-"))
    start = date(y, m, 1)
    end = date(y+1, 1, 1) - timedelta(days=1) if m == 12 else date(y, m+1, 1) - timedelta(days=1)

    emp_stmt = select(Employee).where(Employee.status == 'active')
    if employee_id:
        emp_stmt = emp_stmt.where(Employee.id == employee_id)
    emps = (await db.execute(emp_stmt)).scalars().all()

    result = []
    for emp in emps:
        # 品牌岗位
        ebps = (await db.execute(
            select(EmployeeBrandPosition).where(EmployeeBrandPosition.employee_id == emp.id)
        )).scalars().all()
        brand_positions = [
            {"brand_name": ebp.brand.name if ebp.brand else None,
             "position": ebp.position.name if ebp.position else ebp.position_code,
             "is_primary": ebp.is_primary}
            for ebp in ebps
        ]

        # 销售目标（员工级）- 取本月目标，仅看已审批通过的
        target_stmt = select(SalesTarget).where(
            SalesTarget.target_level == 'employee',
            SalesTarget.employee_id == emp.id,
            SalesTarget.target_year == y,
            SalesTarget.status == 'approved',
        )
        targets = (await db.execute(target_stmt)).scalars().all()
        month_target = next((t for t in targets if t.target_month == m), None)
        year_target = next((t for t in targets if t.target_month is None), None)

        # 本月实际销售额 + 回款
        actual_sales = (await db.execute(
            select(func.coalesce(func.sum(Order.total_amount), 0)).where(
                Order.salesman_id == emp.id,
                extract("year", Order.created_at) == y,
                extract("month", Order.created_at) == m,
            )
        )).scalar_one()
        actual_receipt = (await db.execute(
            select(func.coalesce(func.sum(Receipt.amount), 0))
            .select_from(Receipt).join(Order, Order.id == Receipt.order_id, isouter=True)
            .where(
                Order.salesman_id == emp.id,
                Receipt.status == 'confirmed',  # 只算财务已确认的收款
                extract("year", Receipt.receipt_date) == y,
                extract("month", Receipt.receipt_date) == m,
            )
        )).scalar_one()
        actual_sales = float(actual_sales or 0)
        actual_receipt = float(actual_receipt or 0)

        # 考勤
        checkins = (await db.execute(
            select(CheckinRecord).where(
                CheckinRecord.employee_id == emp.id,
                CheckinRecord.checkin_date.between(start, end),
            )
        )).scalars().all()
        late_times = sum(1 for c in checkins if c.status == 'late')
        late_over30 = sum(1 for c in checkins if c.status == 'late_over30')
        work_days = len({c.checkin_date for c in checkins if c.checkin_type == 'work_in'})

        leaves = (await db.execute(
            select(LeaveRequest).where(
                LeaveRequest.employee_id == emp.id,
                LeaveRequest.status == 'approved',
                LeaveRequest.start_date <= end,
                LeaveRequest.end_date >= start,
            )
        )).scalars().all()
        leave_days = sum(float(l.total_days or 0) for l in leaves if l.leave_type != 'overtime_off')
        overtime_off_days = sum(float(l.total_days or 0) for l in leaves if l.leave_type == 'overtime_off')

        # 有效拜访
        valid_visits = (await db.execute(
            select(func.count(CustomerVisit.id)).where(
                CustomerVisit.employee_id == emp.id,
                CustomerVisit.visit_date.between(start, end),
                CustomerVisit.is_valid == True,
            )
        )).scalar_one()

        # 佣金（从工资单取）
        salary = (await db.execute(
            select(SalaryRecord).where(
                SalaryRecord.employee_id == emp.id,
                SalaryRecord.period == period,
            )
        )).scalar_one_or_none()

        # KPI
        assess = (await db.execute(
            select(AssessmentItem).where(
                AssessmentItem.employee_id == emp.id,
                AssessmentItem.period == period,
            )
        )).scalars().all()

        month_t_sales = float(month_target.sales_target) if month_target else 0
        month_t_receipt = float(month_target.receipt_target) if month_target else 0

        result.append({
            "employee_id": emp.id,
            "employee_name": emp.name,
            "employee_no": emp.employee_no,
            "position": emp.position,
            "brand_positions": brand_positions,
            # 销售
            "sales_target_month": month_t_sales,
            "sales_target_year": float(year_target.sales_target) if year_target else 0,
            "actual_sales": actual_sales,
            "sales_completion": round(actual_sales / month_t_sales, 4) if month_t_sales > 0 else 0,
            # 回款
            "receipt_target_month": month_t_receipt,
            "receipt_target_year": float(year_target.receipt_target) if year_target else 0,
            "actual_receipt": actual_receipt,
            "receipt_completion": round(actual_receipt / month_t_receipt, 4) if month_t_receipt > 0 else 0,
            # 考勤
            "work_days": work_days,
            "late_times": late_times,
            "late_over30_times": late_over30,
            "leave_days": leave_days,
            "overtime_off_days": overtime_off_days,
            "valid_visits": int(valid_visits or 0),
            "is_full_attendance": (late_times == 0 and late_over30 == 0 and leave_days == 0),
            # 佣金
            "commission_total": float(salary.commission_total) if salary else 0,
            "manager_share_total": float(salary.manager_share_total) if salary else 0,
            "subsidy_total": float(salary.manufacturer_subsidy_total) if salary else 0,
            "salary_actual_pay": float(salary.actual_pay) if salary else 0,
            "salary_status": salary.status if salary else None,
            "salary_record_id": salary.id if salary else None,
            # KPI
            "assessment_items": [
                {
                    "item_code": a.item_code, "item_name": a.item_name,
                    "target_value": float(a.target_value), "actual_value": float(a.actual_value),
                    "completion_rate": float(a.completion_rate), "earned_amount": float(a.earned_amount),
                }
                for a in assess
            ],
        })
    return result


@router.post("/refresh-assessment-actual")
async def refresh_assessment_actual(
    user: CurrentUser,
    period: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """扫描本月订单/客户，自动刷新 AssessmentItem.actual_value。
    支持的 item_code:
      - kpi_revenue: 本月回款合计
      - kpi_customers: 本月有订单的客户数
    """
    require_role(user, "boss", "hr", "sales_manager")
    y, m = map(int, period.split("-"))
    items = (await db.execute(
        select(AssessmentItem).where(AssessmentItem.period == period)
    )).scalars().all()
    updated = 0
    for it in items:
        actual = None
        if it.item_code == 'kpi_revenue':
            actual = (await db.execute(
                select(func.coalesce(func.sum(Receipt.amount), 0))
                .select_from(Receipt).join(Order, Order.id == Receipt.order_id, isouter=True)
                .where(
                    Order.salesman_id == it.employee_id,
                    Receipt.status == 'confirmed',  # 只算财务已确认的收款
                    extract("year", Receipt.receipt_date) == y,
                    extract("month", Receipt.receipt_date) == m,
                )
            )).scalar_one()
        elif it.item_code == 'kpi_customers':
            actual = (await db.execute(
                select(func.count(func.distinct(Order.customer_id))).where(
                    Order.salesman_id == it.employee_id,
                    extract("year", Order.created_at) == y,
                    extract("month", Order.created_at) == m,
                )
            )).scalar_one()
        if actual is not None:
            it.actual_value = Decimal(str(actual))
            # 重算 earned_amount
            if it.target_value and it.target_value > 0:
                rate = Decimal(str(actual)) / it.target_value
            else:
                rate = Decimal("0")
            it.completion_rate = rate
            if rate < Decimal("0.5"):
                it.earned_amount = Decimal("0")
            else:
                it.earned_amount = (it.item_amount * rate).quantize(Decimal("0.01"))
            updated += 1
    await db.flush()
    return {"detail": f"已刷新 {updated} 项考核实际值"}


@router.get("/me")
async def my_dashboard(
    user: CurrentUser,
    period: Optional[str] = Query(None, description="默认本月"),
    db: AsyncSession = Depends(get_db),
):
    """当前登录员工的个人绩效面板"""
    from datetime import date as _d
    if not period:
        now = datetime.now()
        period = f"{now.year}-{str(now.month).zfill(2)}"
    emp_id = user.get("employee_id")
    if not emp_id:
        raise HTTPException(400, "账号未绑定员工")
    result = await employee_monthly(user=user, period=period, employee_id=emp_id, db=db)
    if not result:
        raise HTTPException(404, "未找到绩效数据")
    data = result[0]

    # 额外：我的年度目标
    y, _ = map(int, period.split("-"))
    year_targets = (await db.execute(
        select(SalesTarget).where(
            SalesTarget.target_level == 'employee',
            SalesTarget.employee_id == emp_id,
            SalesTarget.target_year == y,
            SalesTarget.target_month.is_(None),
            SalesTarget.status == 'approved',
        )
    )).scalars().all()
    data["year_targets"] = [
        {"brand_name": t.brand.name if t.brand else None,
         "sales_target": float(t.sales_target),
         "receipt_target": float(t.receipt_target)}
        for t in year_targets
    ]
    # 历史 3 个月工资单
    histories = (await db.execute(
        select(SalaryRecord).where(SalaryRecord.employee_id == emp_id)
        .order_by(SalaryRecord.period.desc()).limit(6)
    )).scalars().all()
    data["salary_history"] = [
        {"period": s.period, "total_pay": float(s.total_pay),
         "actual_pay": float(s.actual_pay), "status": s.status,
         "payment_voucher_urls": s.payment_voucher_urls or [],
         "paid_at": str(s.paid_at) if s.paid_at else None}
        for s in histories
    ]
    return data


@router.post("/init-assessment-items")
async def init_assessment_items(
    user: CurrentUser,
    period: str = Query(..., description="YYYY-MM"),
    db: AsyncSession = Depends(get_db),
):
    """为所有业务员/业务经理初始化本月考核项脚手架：
       - kpi_revenue: 回款金额（金额 ¥1000，目标取 sales_target 表 employee 级月度回款目标）
       - kpi_customers: 活跃客户数（金额 ¥500，目标默认 30 家，如有目标则用员工级 employee_target.customer 后续可扩展）
    只为已存在 EmployeeBrandPosition(salesman / sales_manager) 的员工创建，避免给财务/仓管乱挂。
    幂等：已有同 period + item_code 不重复创建。
    """
    require_role(user, "boss", "hr")
    from app.models.payroll import EmployeeBrandPosition

    y, m = map(int, period.split("-"))

    # 找所有销售岗员工
    ebps = (await db.execute(
        select(EmployeeBrandPosition).where(
            EmployeeBrandPosition.position_code.in_(['salesman', 'sales_manager'])
        )
    )).scalars().all()
    emp_ids = list({e.employee_id for e in ebps})
    created = 0
    for eid in emp_ids:
        # 取该员工本月销售目标（任意品牌汇总）作为 kpi_revenue 的 target
        t_sum = (await db.execute(
            select(func.coalesce(func.sum(SalesTarget.receipt_target), 0)).where(
                SalesTarget.target_level == 'employee',
                SalesTarget.employee_id == eid,
                SalesTarget.target_year == y,
                SalesTarget.target_month == m,
                SalesTarget.status == 'approved',
            )
        )).scalar_one()
        revenue_target = Decimal(str(t_sum))

        # kpi_revenue
        has_revenue = (await db.execute(
            select(AssessmentItem).where(
                AssessmentItem.employee_id == eid,
                AssessmentItem.period == period,
                AssessmentItem.item_code == 'kpi_revenue',
            )
        )).scalar_one_or_none()
        if not has_revenue:
            db.add(AssessmentItem(
                id=__import__("uuid").uuid4().hex,
                employee_id=eid, period=period,
                item_code='kpi_revenue', item_name='回款金额',
                item_amount=Decimal("1000"),
                target_value=revenue_target,
                actual_value=Decimal("0"),
                completion_rate=Decimal("0"),
                earned_amount=Decimal("0"),
            ))
            created += 1

        # kpi_customers
        has_cust = (await db.execute(
            select(AssessmentItem).where(
                AssessmentItem.employee_id == eid,
                AssessmentItem.period == period,
                AssessmentItem.item_code == 'kpi_customers',
            )
        )).scalar_one_or_none()
        if not has_cust:
            db.add(AssessmentItem(
                id=__import__("uuid").uuid4().hex,
                employee_id=eid, period=period,
                item_code='kpi_customers', item_name='活跃客户数',
                item_amount=Decimal("500"),
                target_value=Decimal("30"),
                actual_value=Decimal("0"),
                completion_rate=Decimal("0"),
                earned_amount=Decimal("0"),
            ))
            created += 1

    await db.flush()
    # 创建完立即扫订单填 actual_value
    items = (await db.execute(
        select(AssessmentItem).where(AssessmentItem.period == period)
    )).scalars().all()
    refreshed = 0
    for it in items:
        actual = None
        if it.item_code == 'kpi_revenue':
            actual = (await db.execute(
                select(func.coalesce(func.sum(Receipt.amount), 0))
                .select_from(Receipt).join(Order, Order.id == Receipt.order_id, isouter=True)
                .where(
                    Order.salesman_id == it.employee_id,
                    Receipt.status == 'confirmed',  # 只算财务已确认的收款
                    extract("year", Receipt.receipt_date) == y,
                    extract("month", Receipt.receipt_date) == m,
                )
            )).scalar_one()
        elif it.item_code == 'kpi_customers':
            actual = (await db.execute(
                select(func.count(func.distinct(Order.customer_id))).where(
                    Order.salesman_id == it.employee_id,
                    extract("year", Order.created_at) == y,
                    extract("month", Order.created_at) == m,
                )
            )).scalar_one()
        if actual is not None:
            it.actual_value = Decimal(str(actual))
            if it.target_value and it.target_value > 0:
                rate = Decimal(str(actual)) / it.target_value
            else:
                rate = Decimal("0")
            it.completion_rate = rate
            if rate < Decimal("0.5"):
                it.earned_amount = Decimal("0")
            else:
                it.earned_amount = (it.item_amount * rate).quantize(Decimal("0.01"))
            refreshed += 1
    await db.flush()
    return {"detail": f"已初始化 {created} 项考核，刷新 {refreshed} 项实际值"}


@router.get("/employee-trend")
async def employee_trend(
    user: CurrentUser,
    employee_id: Optional[str] = Query(None, description="不传=当前登录员工"),
    months: int = Query(6, ge=3, le=24),
    db: AsyncSession = Depends(get_db),
):
    """员工近 N 个月销售/回款/提成/工资 趋势"""
    from datetime import date as _d, datetime as _dt
    from sqlalchemy import extract as _ext

    eid = employee_id or user.get("employee_id")
    if not eid:
        raise HTTPException(400, "未指定员工")

    emp = await db.get(Employee, eid)
    if not emp:
        raise HTTPException(404, "员工不存在")

    now = _dt.now()
    # 生成月份列表（近 N 个月，从最早到最近）
    periods = []
    y, m = now.year, now.month
    for _ in range(months):
        periods.append((y, m))
        m -= 1
        if m == 0:
            m = 12; y -= 1
    periods.reverse()

    result = []
    for y, m in periods:
        period_str = f"{y}-{str(m).zfill(2)}"
        # 销售 & 回款
        s = (await db.execute(
            select(func.coalesce(func.sum(Order.total_amount), 0)).where(
                Order.salesman_id == eid,
                _ext("year", Order.created_at) == y,
                _ext("month", Order.created_at) == m,
            )
        )).scalar_one()
        rc = (await db.execute(
            select(func.coalesce(func.sum(Receipt.amount), 0))
            .select_from(Receipt).join(Order, Order.id == Receipt.order_id, isouter=True)
            .where(
                Order.salesman_id == eid,
                Receipt.status == 'confirmed',  # 只算财务已确认的收款
                _ext("year", Receipt.receipt_date) == y,
                _ext("month", Receipt.receipt_date) == m,
            )
        )).scalar_one()

        # 目标（月度）
        target = (await db.execute(
            select(SalesTarget).where(
                SalesTarget.target_level == 'employee',
                SalesTarget.employee_id == eid,
                SalesTarget.target_year == y,
                SalesTarget.target_month == m,
                SalesTarget.status == 'approved',
            )
        )).scalar_one_or_none()

        # 工资单
        rec = (await db.execute(
            select(SalaryRecord).where(
                SalaryRecord.employee_id == eid,
                SalaryRecord.period == period_str,
            )
        )).scalar_one_or_none()

        result.append({
            "period": period_str,
            "sales": float(s or 0),
            "receipt": float(rc or 0),
            "sales_target": float(target.sales_target) if target else 0,
            "receipt_target": float(target.receipt_target) if target else 0,
            "commission": float(rec.commission_total) if rec else 0,
            "manager_share": float(rec.manager_share_total) if rec else 0,
            "bonus": float(rec.bonus_other) if rec else 0,
            "actual_pay": float(rec.actual_pay) if rec else 0,
        })

    return {
        "employee_id": eid,
        "employee_name": emp.name,
        "trend": result,
    }
