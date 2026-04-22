"""
MCP 操作类工具 — 写入数据（受 RLS + 角色约束）。
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.auth import require_mcp_employee, require_mcp_role
from app.mcp.deps import get_mcp_db
from app.services.audit_service import log_audit

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# 11. 创建订单
# ═══════════════════════════════════════════════════════════════════

class MCPCreateOrderRequest(BaseModel):
    customer_id: str
    salesman_id: str
    policy_template_id: str
    settlement_mode: str  # customer_pay / employee_pay / company_pay
    items: list[dict]  # [{product_id, quantity, quantity_unit}]
    deal_unit_price: Optional[float] = None
    advance_payer_id: Optional[str] = None
    warehouse_id: Optional[str] = None
    notes: Optional[str] = None


@router.post("/create-order")
async def mcp_create_order(body: MCPCreateOrderRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建订单。指导价从政策模板强制读取。"""
    from app.models.policy_template import PolicyTemplate
    from app.models.product import Product
    from app.models.order import Order, OrderItem

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "salesman", "sales_manager")
    # salesman 身份硬绑定：不信 body 传入的 salesman_id
    roles = user.get("roles") or []
    if "admin" not in roles and "boss" not in roles and "sales_manager" not in roles:
        emp_id = user.get("employee_id")
        if not emp_id:
            raise HTTPException(400, "当前用户未绑定员工档案，无法建单")
        body.salesman_id = emp_id

    tmpl = await db.get(PolicyTemplate, body.policy_template_id)
    if not tmpl or not tmpl.is_active:
        raise HTTPException(400, "政策模板不存在或已停用")
    guide_price = Decimal(str(tmpl.required_unit_price or 0))
    customer_price = Decimal(str(body.deal_unit_price or tmpl.customer_unit_price or guide_price))
    brand_id = tmpl.brand_id

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    order = Order(
        id=str(uuid.uuid4()), order_no=f"SO-{ts}-{uuid.uuid4().hex[:6]}",
        customer_id=body.customer_id, salesman_id=body.salesman_id,
        brand_id=brand_id, settlement_mode=body.settlement_mode,
        advance_payer_id=body.advance_payer_id, warehouse_id=body.warehouse_id,
        policy_template_id=tmpl.id, notes=body.notes,
    )
    total = Decimal("0")
    total_bottles = 0
    for it in body.items:
        prod = await db.get(Product, it["product_id"])
        bpc = prod.bottles_per_case if prod else 6
        bottles = it["quantity"] * bpc if it.get("quantity_unit", "箱") == "箱" else it["quantity"]
        order.items.append(OrderItem(
            id=str(uuid.uuid4()), order_id=order.id,
            product_id=it["product_id"], quantity=it["quantity"],
            quantity_unit=it.get("quantity_unit", "箱"), unit_price=guide_price,
        ))
        total += guide_price * bottles
        total_bottles += bottles

    order.total_amount = total
    order.deal_unit_price = customer_price
    order.deal_amount = customer_price * total_bottles
    order.policy_gap = total - order.deal_amount
    order.policy_value = tmpl.total_policy_value
    order.policy_surplus = (tmpl.total_policy_value or Decimal("0")) - order.policy_gap

    if body.settlement_mode in ("customer_pay", "employee_pay"):
        order.customer_paid_amount = total
    elif body.settlement_mode == "company_pay":
        order.customer_paid_amount = order.deal_amount
    order.policy_receivable = order.policy_gap if body.settlement_mode != "customer_pay" else Decimal("0")

    db.add(order)
    await db.flush()
    await log_audit(db, action="create_order", entity_type="Order", entity_id=order.id, user=user)
    return {"order_no": order.order_no, "total_amount": float(total), "customer_paid_amount": float(order.customer_paid_amount)}


# ═══════════════════════════════════════════════════════════════════
# 12. 登记收款凭证
# ═══════════════════════════════════════════════════════════════════

class MCPUploadPaymentRequest(BaseModel):
    order_no: str
    amount: float
    source_type: str = "customer"  # customer / employee_advance


@router.post("/register-payment")
async def mcp_register_payment(body: MCPUploadPaymentRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 登记一笔收款（等价于前端 upload-payment-voucher）。"""
    from app.models.order import Order
    from app.models.finance import Receipt
    from app.models.product import Account
    from app.models.base import PaymentStatus, OrderPaymentMethod
    from app.api.routes.accounts import record_fund_flow

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance", "salesman")
    order = (await db.execute(select(Order).where(Order.order_no == body.order_no))).scalar_one_or_none()
    if not order:
        raise HTTPException(404, f"订单 {body.order_no} 不存在")
    if body.amount <= 0:
        raise HTTPException(400, "金额必须大于 0")

    master_cash = (await db.execute(
        select(Account).where(Account.level == 'master', Account.account_type == 'cash')
    )).scalar_one_or_none()
    if not master_cash:
        raise HTTPException(400, "未配置公司总资金池")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    amt = Decimal(str(body.amount))
    receipt = Receipt(
        id=str(uuid.uuid4()), receipt_no=f"RC-{ts}-{uuid.uuid4().hex[:6]}",
        customer_id=order.customer_id, order_id=order.id, brand_id=order.brand_id,
        account_id=master_cash.id, amount=amt,
        payment_method=OrderPaymentMethod.BANK,
        receipt_date=datetime.now(timezone.utc).date(),
        source_type=body.source_type,
    )
    db.add(receipt)
    master_cash.balance += amt
    await record_fund_flow(db, account_id=master_cash.id, flow_type='credit', amount=amt,
        balance_after=master_cash.balance, related_type='receipt', related_id=receipt.id,
        notes=f"MCP收款 {order.order_no}", brand_id=order.brand_id)
    await db.flush()

    total_received = (await db.execute(
        select(func.coalesce(func.sum(Receipt.amount), 0)).where(Receipt.order_id == order.id)
    )).scalar_one()
    target = order.customer_paid_amount or order.total_amount
    if Decimal(str(total_received)) >= target:
        order.payment_status = PaymentStatus.FULLY_PAID
    elif total_received > 0:
        order.payment_status = PaymentStatus.PARTIALLY_PAID
    await db.flush()

    return {"receipt_no": receipt.receipt_no, "total_received": float(total_received),
            "target": float(target), "payment_status": order.payment_status}


# ═══════════════════════════════════════════════════════════════════
# 13. 创建客户
# ═══════════════════════════════════════════════════════════════════

class MCPCreateCustomerRequest(BaseModel):
    code: str
    name: str
    brand_id: str
    salesman_id: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    settlement_mode: str = "cash"


@router.post("/create-customer")
async def mcp_create_customer(body: MCPCreateCustomerRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建客户并绑定品牌。"""
    from app.models.customer import Customer, CustomerBrandSalesman
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "salesman", "sales_manager")
    # salesman 建客户：salesman_id 强制绑定本人
    roles = user.get("roles") or []
    if "admin" not in roles and "boss" not in roles and "sales_manager" not in roles:
        emp_id = user.get("employee_id")
        if not emp_id:
            raise HTTPException(400, "当前用户未绑定员工档案")
        body.salesman_id = emp_id

    obj = Customer(id=str(uuid.uuid4()), code=body.code, name=body.name,
                   contact_name=body.contact_name, contact_phone=body.contact_phone,
                   settlement_mode=body.settlement_mode, salesman_id=body.salesman_id)
    db.add(obj)
    await db.flush()
    if body.brand_id and body.salesman_id:
        db.add(CustomerBrandSalesman(id=str(uuid.uuid4()), customer_id=obj.id,
                                     brand_id=body.brand_id, salesman_id=body.salesman_id))
        await db.flush()
    return {"customer_id": obj.id, "code": obj.code, "name": obj.name}


# ═══════════════════════════════════════════════════════════════════
# 14. 创建请假
# ═══════════════════════════════════════════════════════════════════

class MCPCreateLeaveRequest(BaseModel):
    employee_id: str
    leave_type: str  # sick/personal/annual/overtime_off
    start_date: str  # YYYY-MM-DD
    end_date: str
    total_days: float
    reason: Optional[str] = None


@router.post("/create-leave-request")
async def mcp_create_leave(body: MCPCreateLeaveRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 提交请假申请。"""
    from app.models.attendance import LeaveRequest
    from datetime import date
    user = db.info.get("mcp_user", {})
    require_mcp_employee(user)
    # employee_id 强制绑定当前用户，不信 body 传入（防替他人请假）
    # 例外：admin/boss 可代提交
    roles = user.get("roles") or []
    if "admin" not in roles and "boss" not in roles:
        emp_id = user.get("employee_id")
        if not emp_id:
            raise HTTPException(400, "当前用户未绑定员工档案")
        body.employee_id = emp_id
    # 校验员工存在
    from app.models.user import Employee
    emp = await db.get(Employee, body.employee_id)
    if not emp:
        raise HTTPException(400, f"员工 {body.employee_id} 不存在")
    # 日期解析
    try:
        start = date.fromisoformat(body.start_date)
        end = date.fromisoformat(body.end_date)
    except ValueError:
        raise HTTPException(400, f"日期格式错误，需要 YYYY-MM-DD，收到 {body.start_date} / {body.end_date}")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    obj = LeaveRequest(
        id=str(uuid.uuid4()), request_no=f"LV-{ts}-{uuid.uuid4().hex[:6]}",
        employee_id=body.employee_id, leave_type=body.leave_type,
        start_date=start, end_date=end,
        total_days=Decimal(str(body.total_days)), reason=body.reason, status="pending",
    )
    db.add(obj)
    await db.flush()
    return {"request_no": obj.request_no, "employee": emp.name, "status": "pending"}


# ═══════════════════════════════════════════════════════════════════
# 15. 生成工资单
# ═══════════════════════════════════════════════════════════════════

class MCPGenerateSalaryRequest(BaseModel):
    period: str  # "2026-04"
    overwrite: bool = False


@router.post("/generate-salary")
async def mcp_generate_salary(body: MCPGenerateSalaryRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 一键生成本期工资单（直接调用后端生成逻辑）。"""
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")
    from app.api.routes.payroll import generate_salary_records, GenerateSalaryRequest
    internal_body = GenerateSalaryRequest(period=body.period, overwrite=body.overwrite)
    return await generate_salary_records(body=internal_body, user=user, db=db)


# ═══════════════════════════════════════════════════════════════════
# 16. 生成厂家补贴应收
# ═══════════════════════════════════════════════════════════════════

class MCPGenerateSubsidyRequest(BaseModel):
    period: str

@router.post("/generate-subsidy-expected")
async def mcp_generate_subsidy(body: MCPGenerateSubsidyRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 生成本月厂家补贴应收（直接执行）。"""
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")
    from app.models.payroll import EmployeeBrandPosition, ManufacturerSalarySubsidy
    ebps = (await db.execute(
        select(EmployeeBrandPosition).where(EmployeeBrandPosition.manufacturer_subsidy > 0)
    )).scalars().all()
    created, skipped = 0, 0
    for ebp in ebps:
        existing = (await db.execute(
            select(ManufacturerSalarySubsidy).where(
                ManufacturerSalarySubsidy.employee_id == ebp.employee_id,
                ManufacturerSalarySubsidy.brand_id == ebp.brand_id,
                ManufacturerSalarySubsidy.period == body.period,
            )
        )).scalar_one_or_none()
        if existing:
            skipped += 1; continue
        db.add(ManufacturerSalarySubsidy(
            id=str(uuid.uuid4()), employee_id=ebp.employee_id, brand_id=ebp.brand_id,
            period=body.period, subsidy_amount=ebp.manufacturer_subsidy, status='pending',
        ))
        created += 1
    await db.flush()
    return {"created": created, "skipped": skipped, "period": body.period}


# ═══════════════════════════════════════════════════════════════════
# 17. 创建员工
# ═══════════════════════════════════════════════════════════════════

class MCPCreateEmployeeRequest(BaseModel):
    employee_no: str
    name: str
    position: Optional[str] = None
    phone: Optional[str] = None
    hire_date: Optional[str] = None  # YYYY-MM-DD
    social_security: float = 0
    company_social_security: float = 0
    expected_manufacturer_subsidy: float = 0


@router.post("/create-employee")
async def mcp_create_employee(body: MCPCreateEmployeeRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建员工档案。需要 admin/boss/hr 权限。"""
    from app.models.user import Employee
    from datetime import date
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "hr")
    # 检查工号唯一
    existing = (await db.execute(select(Employee).where(Employee.employee_no == body.employee_no))).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"工号 {body.employee_no} 已存在（{existing.name}）")
    emp = Employee(
        id=str(uuid.uuid4()), employee_no=body.employee_no, name=body.name,
        position=body.position, phone=body.phone,
        hire_date=date.fromisoformat(body.hire_date) if body.hire_date else None,
        social_security=Decimal(str(body.social_security)),
        company_social_security=Decimal(str(body.company_social_security)),
        expected_manufacturer_subsidy=Decimal(str(body.expected_manufacturer_subsidy)),
    )
    db.add(emp)
    await db.flush()
    await log_audit(db, action="create_employee", entity_type="Employee", entity_id=emp.id, user=user)
    return {"employee_id": emp.id, "employee_no": emp.employee_no, "name": emp.name}


# ═══════════════════════════════════════════════════════════════════
# 18. 查询员工列表
# ═══════════════════════════════════════════════════════════════════

class MCPQueryEmployeesRequest(BaseModel):
    keyword: Optional[str] = None
    status: Optional[str] = None
    brand_id: Optional[str] = None
    limit: int = 50


@router.post("/query-employees")
async def mcp_query_employees(body: MCPQueryEmployeesRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 查询员工列表。"""
    from app.models.user import Employee
    from app.models.payroll import EmployeeBrandPosition
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "hr", "finance", "sales_manager")
    stmt = select(Employee)
    if body.keyword:
        kw = f"%{body.keyword}%"
        stmt = stmt.where(Employee.name.ilike(kw) | Employee.employee_no.ilike(kw))
    if body.status:
        stmt = stmt.where(Employee.status == body.status)
    if body.brand_id:
        stmt = stmt.join(EmployeeBrandPosition, Employee.id == EmployeeBrandPosition.employee_id).where(EmployeeBrandPosition.brand_id == body.brand_id)
    stmt = stmt.order_by(Employee.employee_no).limit(body.limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [{
        "id": e.id, "employee_no": e.employee_no, "name": e.name,
        "position": e.position, "phone": e.phone, "status": e.status,
    } for e in rows]


# ═══════════════════════════════════════════════════════════════════
# 19. 绑定员工品牌岗位
# ═══════════════════════════════════════════════════════════════════

class MCPBindBrandPositionRequest(BaseModel):
    employee_id: str
    brand_id: str
    position_code: str
    commission_rate: Optional[float] = None
    manufacturer_subsidy: float = 0
    is_primary: bool = False


@router.post("/bind-employee-brand")
async def mcp_bind_brand(body: MCPBindBrandPositionRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 绑定员工到品牌×岗位。"""
    from app.models.payroll import EmployeeBrandPosition
    from app.models.user import Employee
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "hr")
    emp = await db.get(Employee, body.employee_id)
    if not emp:
        raise HTTPException(404, f"员工 {body.employee_id} 不存在")
    existing = (await db.execute(
        select(EmployeeBrandPosition).where(
            EmployeeBrandPosition.employee_id == body.employee_id,
            EmployeeBrandPosition.brand_id == body.brand_id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"员工 {emp.name} 已绑定此品牌")
    if body.is_primary:
        others = (await db.execute(
            select(EmployeeBrandPosition).where(
                EmployeeBrandPosition.employee_id == body.employee_id,
                EmployeeBrandPosition.is_primary == True,
            )
        )).scalars().all()
        for o in others:
            o.is_primary = False
    ebp = EmployeeBrandPosition(
        id=str(uuid.uuid4()), employee_id=body.employee_id,
        brand_id=body.brand_id, position_code=body.position_code,
        commission_rate=Decimal(str(body.commission_rate)) if body.commission_rate is not None else None,
        manufacturer_subsidy=Decimal(str(body.manufacturer_subsidy)),
        is_primary=body.is_primary,
    )
    db.add(ebp)
    await db.flush()
    return {"id": ebp.id, "employee": emp.name, "brand_id": body.brand_id, "position": body.position_code, "is_primary": body.is_primary}


# ═══════════════════════════════════════════════════════════════════
# 20. 创建用户账号
# ═══════════════════════════════════════════════════════════════════

class MCPCreateUserRequest(BaseModel):
    username: str
    password: str
    employee_id: Optional[str] = None
    role_codes: list[str] = []


@router.post("/create-user")
async def mcp_create_user(body: MCPCreateUserRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建登录账号并分配角色。需要 admin/boss 权限。"""
    from app.models.user import User, UserRole, Role
    from app.core.security import get_password_hash
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss")
    existing = (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"用户名 '{body.username}' 已存在")
    new_user = User(
        id=str(uuid.uuid4()), username=body.username,
        hashed_password=get_password_hash(body.password),
        employee_id=body.employee_id,
    )
    db.add(new_user)
    await db.flush()
    if body.role_codes:
        roles = (await db.execute(select(Role).where(Role.code.in_(body.role_codes)))).scalars().all()
        for r in roles:
            db.add(UserRole(id=str(uuid.uuid4()), user_id=new_user.id, role_id=r.id))
        await db.flush()
    return {"user_id": new_user.id, "username": new_user.username, "roles": body.role_codes}


# ═══════════════════════════════════════════════════════════════════
# 21. 创建资金调拨申请
# ═══════════════════════════════════════════════════════════════════

class MCPCreateTransferRequest(BaseModel):
    to_brand_name: Optional[str] = None  # 品牌名（自动查 brand cash 账户）
    to_account_id: Optional[str] = None  # 或直接指定账户 ID
    amount: float
    notes: Optional[str] = None


@router.post("/create-fund-transfer")
async def mcp_create_fund_transfer(body: MCPCreateTransferRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建资金调拨申请（master → 品牌现金/融资）。需老板审批后才执行。"""
    from app.models.product import Account, Brand
    from app.api.routes.accounts import record_fund_flow
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    # 源：master 现金池
    master = (await db.execute(
        select(Account).where(Account.level == 'master', Account.account_type == 'cash')
    )).scalar_one_or_none()
    if not master:
        raise HTTPException(400, "未找到公司总资金池")

    # 目标：按品牌名查或直接用 ID
    to_acc = None
    if body.to_account_id:
        to_acc = await db.get(Account, body.to_account_id)
    elif body.to_brand_name:
        brand = (await db.execute(select(Brand).where(Brand.name.ilike(f"%{body.to_brand_name}%")))).scalar_one_or_none()
        if not brand:
            raise HTTPException(400, f"品牌 '{body.to_brand_name}' 不存在")
        to_acc = (await db.execute(
            select(Account).where(Account.brand_id == brand.id, Account.account_type == 'cash', Account.level == 'project')
        )).scalar_one_or_none()
    if not to_acc:
        raise HTTPException(400, "未找到目标账户")
    if to_acc.level != 'project':
        raise HTTPException(400, "只能拨款到品牌项目账户")
    if to_acc.account_type not in ('cash', 'financing'):
        raise HTTPException(400, "只能拨款到现金或融资账户")

    amt = Decimal(str(body.amount))
    if amt <= 0:
        raise HTTPException(400, "金额必须大于 0")
    if master.balance < amt:
        raise HTTPException(400, f"总资金池余额不足：¥{master.balance}，需拨 ¥{amt}")

    # 创建待审批流水
    ff = await record_fund_flow(
        db, account_id=master.id, flow_type='transfer_pending', amount=amt,
        balance_after=master.balance, related_type='transfer_pending', related_id=to_acc.id,
        notes=body.notes or f"调拨到 {to_acc.name}", created_by=user.get('employee_id'),
        brand_id=to_acc.brand_id,
    )
    await db.flush()
    return {"transfer_id": ff.id, "from": master.name, "to": to_acc.name, "amount": float(amt), "status": "待审批"}
