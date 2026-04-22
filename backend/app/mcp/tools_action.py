"""
MCP 操作类工具 — 写入数据（受 RLS + 角色约束）。
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Optional

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
    customer_type: Literal["channel", "group_purchase"] = "channel"
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
                   customer_type=body.customer_type,
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

    # 源账户：master 现金池
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


# ═══════════════════════════════════════════════════════════════════
# 22. 编辑客户信息
# ═══════════════════════════════════════════════════════════════════

class MCPUpdateCustomerRequest(BaseModel):
    customer_id: str
    name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    settlement_mode: Optional[str] = None


@router.post("/update-customer")
async def mcp_update_customer(body: MCPUpdateCustomerRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 编辑客户信息。仅更新传入的非空字段。"""
    from app.models.customer import Customer
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "salesman", "sales_manager")

    cust = await db.get(Customer, body.customer_id)
    if not cust:
        raise HTTPException(404, f"客户 {body.customer_id} 不存在")
    updated_fields = []
    if body.name is not None:
        cust.name = body.name
        updated_fields.append("name")
    if body.contact_name is not None:
        cust.contact_name = body.contact_name
        updated_fields.append("contact_name")
    if body.contact_phone is not None:
        cust.contact_phone = body.contact_phone
        updated_fields.append("contact_phone")
    if body.settlement_mode is not None:
        cust.settlement_mode = body.settlement_mode
        updated_fields.append("settlement_mode")
    if not updated_fields:
        raise HTTPException(400, "至少提供一个待更新字段")
    await db.flush()
    await log_audit(db, action="update_customer", entity_type="Customer", entity_id=cust.id, user=user)
    return {"customer_id": cust.id, "updated_fields": updated_fields}


# ═══════════════════════════════════════════════════════════════════
# 23. 创建采购单
# ═══════════════════════════════════════════════════════════════════

class MCPPurchaseItem(BaseModel):
    product_id: str
    quantity: int
    unit_price: float


class MCPCreatePurchaseOrderRequest(BaseModel):
    supplier_id: str
    brand_id: str
    warehouse_id: str
    items: list[MCPPurchaseItem]
    notes: Optional[str] = None


@router.post("/create-purchase-order")
async def mcp_create_purchase_order(body: MCPCreatePurchaseOrderRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建采购单。状态为 pending，需审批后才能执行。"""
    from app.models.purchase import PurchaseOrder, PurchaseOrderItem
    from datetime import datetime, timezone
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "purchase", "warehouse")

    if not body.items:
        raise HTTPException(400, "采购明细不能为空")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    po = PurchaseOrder(
        id=str(uuid.uuid4()),
        po_no=f"PO-{ts}-{uuid.uuid4().hex[:6]}",
        brand_id=body.brand_id,
        supplier_id=body.supplier_id,
        warehouse_id=body.warehouse_id,
        notes=body.notes,
        status="pending",
    )
    total = Decimal("0")
    for it in body.items:
        price = Decimal(str(it.unit_price))
        line_total = price * it.quantity
        total += line_total
        po.items.append(PurchaseOrderItem(
            id=str(uuid.uuid4()),
            po_id=po.id,
            product_id=it.product_id,
            quantity=it.quantity,
            unit_price=price,
        ))
    po.total_amount = total
    db.add(po)
    await db.flush()
    await log_audit(db, action="create_purchase_order", entity_type="PurchaseOrder", entity_id=po.id, user=user)
    return {"po_no": po.po_no, "total_amount": float(total), "status": po.status}


# ═══════════════════════════════════════════════════════════════════
# 24. 创建费用
# ═══════════════════════════════════════════════════════════════════

class MCPCreateExpenseRequest(BaseModel):
    brand_id: str
    category: str  # claim_type: f_class / daily
    amount: float
    description: str
    expense_date: Optional[str] = None  # YYYY-MM-DD


@router.post("/create-expense")
async def mcp_create_expense(body: MCPCreateExpenseRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建费用/报销记录。状态为 pending，需审批。"""
    from app.models.expense_claim import ExpenseClaim
    from datetime import datetime, timezone
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    if body.amount <= 0:
        raise HTTPException(400, "金额必须大于 0")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    claim = ExpenseClaim(
        id=str(uuid.uuid4()),
        claim_no=f"EX-{ts}-{uuid.uuid4().hex[:6]}",
        claim_type=body.category,
        brand_id=body.brand_id,
        title=body.description,
        description=body.description,
        amount=Decimal(str(body.amount)),
        applicant_id=user.get("employee_id"),
        status="pending",
    )
    db.add(claim)
    await db.flush()
    await log_audit(db, action="create_expense", entity_type="ExpenseClaim", entity_id=claim.id, user=user)
    return {"claim_no": claim.claim_no, "amount": float(claim.amount), "status": claim.status}


# ═══════════════════════════════════════════════════════════════════
# 25. 创建稽查案件
# ═══════════════════════════════════════════════════════════════════

class MCPCreateInspectionCaseRequest(BaseModel):
    brand_id: str
    case_type: str  # inspection_violation / market_cleanup / ...
    direction: str  # outflow / inflow
    product_id: Optional[str] = None
    quantity: Optional[int] = None
    quantity_unit: Optional[str] = "瓶"
    deal_unit_price: Optional[float] = None
    purchase_price: Optional[float] = None
    sale_price: Optional[float] = None
    penalty_amount: Optional[float] = None
    notes: Optional[str] = None


@router.post("/create-inspection-case")
async def mcp_create_inspection_case(body: MCPCreateInspectionCaseRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建稽查案件。自动计算 profit_loss。
    A1 亏损公式：profit_loss = -(回收价 - 到手价) * 瓶数。
    """
    from app.models.inspection import InspectionCase
    from datetime import datetime, timezone
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    qty = body.quantity or 0
    deal_price = Decimal(str(body.deal_unit_price or 0))
    purchase_p = Decimal(str(body.purchase_price or 0))
    sale_p = Decimal(str(body.sale_price or 0))
    penalty = Decimal(str(body.penalty_amount or 0))

    # profit_loss 计算：
    # outflow（窜出）：亏损 = -(回收价 - 到手价) * 数量 - 罚款
    # inflow（窜入/回收）：盈利 = (转卖价 - 采购价) * 数量
    if body.direction == "outflow":
        profit_loss = -(deal_price - sale_p) * qty - penalty
    else:
        profit_loss = (sale_p - purchase_p) * qty

    case = InspectionCase(
        id=str(uuid.uuid4()),
        case_no=f"IC-{ts}-{uuid.uuid4().hex[:6]}",
        brand_id=body.brand_id,
        case_type=body.case_type,
        direction=body.direction,
        product_id=body.product_id,
        quantity=qty,
        quantity_unit=body.quantity_unit or "瓶",
        deal_unit_price=deal_price,
        purchase_price=purchase_p,
        resell_price=sale_p,
        penalty_amount=penalty,
        profit_loss=profit_loss,
        notes=body.notes,
        status="pending",
    )
    db.add(case)
    await db.flush()
    await log_audit(db, action="create_inspection_case", entity_type="InspectionCase", entity_id=case.id, user=user)
    return {
        "case_no": case.case_no, "direction": case.direction,
        "profit_loss": float(profit_loss), "status": case.status,
    }


# ═══════════════════════════════════════════════════════════════════
# 26. 创建销售目标
# ═══════════════════════════════════════════════════════════════════

class MCPCreateSalesTargetRequest(BaseModel):
    target_level: str  # company / brand / employee
    target_year: int
    target_month: Optional[int] = None
    brand_id: Optional[str] = None
    employee_id: Optional[str] = None
    sales_target: float
    receipt_target: float


@router.post("/create-sales-target")
async def mcp_create_sales_target(body: MCPCreateSalesTargetRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建销售目标。boss 创建直接 approved；sales_manager 创建走 pending_approval。"""
    from app.models.sales_target import SalesTarget
    from datetime import datetime, timezone
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "sales_manager")

    # 校验 target_level 一致性
    if body.target_level == "brand" and not body.brand_id:
        raise HTTPException(400, "品牌级目标必须指定 brand_id")
    if body.target_level == "employee" and not body.employee_id:
        raise HTTPException(400, "员工级目标必须指定 employee_id")

    roles = user.get("roles") or []
    # boss 建的目标直接 approved
    is_boss = "admin" in roles or "boss" in roles
    now = datetime.now(timezone.utc)

    target = SalesTarget(
        id=str(uuid.uuid4()),
        target_level=body.target_level,
        target_year=body.target_year,
        target_month=body.target_month,
        brand_id=body.brand_id,
        employee_id=body.employee_id,
        sales_target=Decimal(str(body.sales_target)),
        receipt_target=Decimal(str(body.receipt_target)),
        status="approved" if is_boss else "pending_approval",
        submitted_by=user.get("employee_id"),
        submitted_at=now,
        approved_by=user.get("employee_id") if is_boss else None,
        approved_at=now if is_boss else None,
    )
    db.add(target)
    await db.flush()
    return {
        "target_id": target.id, "level": target.target_level,
        "sales_target": float(target.sales_target),
        "receipt_target": float(target.receipt_target),
        "status": target.status,
    }


# ═══════════════════════════════════════════════════════════════════
# 27. 更新订单状态（发货/送达/取消）
# ═══════════════════════════════════════════════════════════════════

class MCPUpdateOrderStatusRequest(BaseModel):
    order_id: str
    action: str  # ship / confirm-delivery / cancel


@router.post("/update-order-status")
async def mcp_update_order_status(body: MCPUpdateOrderStatusRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 更新订单状态。支持 ship（发货）、confirm-delivery（确认送达）、cancel（取消）。"""
    from app.models.order import Order
    from app.models.base import OrderStatus
    from datetime import datetime, timezone
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "warehouse", "salesman")

    order = await db.get(Order, body.order_id)
    if not order:
        raise HTTPException(404, f"订单 {body.order_id} 不存在")

    now = datetime.now(timezone.utc)
    action = body.action

    if action == "ship":
        # 发货：approved → shipped
        if order.status != OrderStatus.APPROVED:
            raise HTTPException(400, f"订单状态为 {order.status}，需要 approved 才能发货")
        order.status = OrderStatus.SHIPPED
        order.shipped_at = now
    elif action == "confirm-delivery":
        # 确认送达：shipped → delivered
        if order.status != OrderStatus.SHIPPED:
            raise HTTPException(400, f"订单状态为 {order.status}，需要 shipped 才能确认送达")
        order.status = OrderStatus.DELIVERED
        order.delivered_at = now
    elif action == "cancel":
        # 取消：pending / approved → rejected
        if order.status not in (OrderStatus.PENDING, OrderStatus.APPROVED,
                                 OrderStatus.POLICY_PENDING_INTERNAL, OrderStatus.POLICY_PENDING_EXTERNAL):
            raise HTTPException(400, f"订单状态为 {order.status}，不能取消")
        order.status = OrderStatus.REJECTED
        order.rejection_reason = "MCP 工具取消"
    else:
        raise HTTPException(400, f"不支持的 action: {action}，可选: ship / confirm-delivery / cancel")

    await db.flush()
    await log_audit(db, action=f"order_{action}", entity_type="Order", entity_id=order.id, user=user)
    return {"order_id": order.id, "order_no": order.order_no, "status": order.status}


# ═══════════════════════════════════════════════════════════════════
# 28. 创建融资单
# ═══════════════════════════════════════════════════════════════════

class MCPCreateFinancingOrderRequest(BaseModel):
    brand_id: str
    amount: float
    interest_rate: Optional[float] = None
    start_date: str  # YYYY-MM-DD
    maturity_date: Optional[str] = None
    bank_name: Optional[str] = None
    notes: Optional[str] = None


@router.post("/create-financing-order")
async def mcp_create_financing_order(body: MCPCreateFinancingOrderRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建融资单。自动查找品牌融资账户，增加账户余额，记录资金流水。"""
    from app.models.financing import FinancingOrder
    from app.models.product import Account
    from app.api.routes.accounts import record_fund_flow
    from datetime import date

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    if body.amount <= 0:
        raise HTTPException(400, "融资金额必须大于 0")

    # 查找品牌的融资账户
    fin_acc = (await db.execute(
        select(Account).where(
            Account.brand_id == body.brand_id,
            Account.account_type == 'financing',
            Account.is_active == True,
        )
    )).scalar_one_or_none()
    if not fin_acc:
        raise HTTPException(400, "该品牌未配置融资账户")

    try:
        start = date.fromisoformat(body.start_date)
        maturity = date.fromisoformat(body.maturity_date) if body.maturity_date else None
    except ValueError:
        raise HTTPException(400, "日期格式错误，需要 YYYY-MM-DD")

    amt = Decimal(str(body.amount))
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    fo = FinancingOrder(
        id=str(uuid.uuid4()),
        order_no=f"FIN-{ts}-{uuid.uuid4().hex[:6]}",
        brand_id=body.brand_id,
        financing_account_id=fin_acc.id,
        amount=amt,
        outstanding_balance=amt,
        interest_rate=Decimal(str(body.interest_rate)) if body.interest_rate is not None else None,
        start_date=start,
        maturity_date=maturity,
        bank_name=body.bank_name,
        notes=body.notes,
        created_by=user.get("employee_id"),
    )
    db.add(fo)

    # 增加融资账户余额
    fin_acc.balance += amt
    await record_fund_flow(
        db, account_id=fin_acc.id, flow_type='credit', amount=amt,
        balance_after=fin_acc.balance, related_type='financing_order', related_id=fo.id,
        notes=f"融资入账 {fo.order_no}", brand_id=body.brand_id,
    )
    await db.flush()
    await log_audit(db, action="create_financing_order", entity_type="FinancingOrder", entity_id=fo.id, user=user)
    return {"order_no": fo.order_no, "amount": float(amt), "status": fo.status}


# ═══════════════════════════════════════════════════════════════════
# 29. 创建商品
# ═══════════════════════════════════════════════════════════════════

class MCPCreateProductRequest(BaseModel):
    code: str
    name: str
    brand_id: str
    bottles_per_case: int = 6
    sale_price: Optional[float] = None
    cost_price: Optional[float] = None
    status: str = "active"


@router.post("/create-product")
async def mcp_create_product(body: MCPCreateProductRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建商品。需要 boss 或 warehouse 权限。"""
    from app.models.product import Product

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "warehouse")

    # 检查 code 唯一
    existing = (await db.execute(select(Product).where(Product.code == body.code))).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"商品编码 {body.code} 已存在（{existing.name}）")

    prod = Product(
        id=str(uuid.uuid4()),
        code=body.code,
        name=body.name,
        brand_id=body.brand_id,
        bottles_per_case=body.bottles_per_case,
        sale_price=Decimal(str(body.sale_price)) if body.sale_price is not None else None,
        purchase_price=Decimal(str(body.cost_price)) if body.cost_price is not None else None,
        status=body.status,
    )
    db.add(prod)
    await db.flush()
    await log_audit(db, action="create_product", entity_type="Product", entity_id=prod.id, user=user)
    return {"product_id": prod.id, "code": prod.code, "name": prod.name}


# ═══════════════════════════════════════════════════════════════════
# 30. 创建供应商
# ═══════════════════════════════════════════════════════════════════

class MCPCreateSupplierRequest(BaseModel):
    code: str
    name: str
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None


@router.post("/create-supplier")
async def mcp_create_supplier(body: MCPCreateSupplierRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建供应商。需要 boss / purchase / warehouse 权限。"""
    from app.models.product import Supplier

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "purchase", "warehouse")

    existing = (await db.execute(select(Supplier).where(Supplier.code == body.code))).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"供应商编码 {body.code} 已存在（{existing.name}）")

    supplier = Supplier(
        id=str(uuid.uuid4()),
        code=body.code,
        name=body.name,
        contact_name=body.contact_name,
        contact_phone=body.contact_phone,
        address=body.address,
    )
    db.add(supplier)
    await db.flush()
    await log_audit(db, action="create_supplier", entity_type="Supplier", entity_id=supplier.id, user=user)
    return {"supplier_id": supplier.id, "code": supplier.code, "name": supplier.name}


# ═══════════════════════════════════════════════════════════════════
# 31. 采购收货
# ═══════════════════════════════════════════════════════════════════

class MCPReceivedItem(BaseModel):
    product_id: str
    received_quantity: int


class MCPReceivePurchaseOrderRequest(BaseModel):
    po_id: str
    received_items: list[MCPReceivedItem]


@router.post("/receive-purchase-order")
async def mcp_receive_purchase_order(body: MCPReceivePurchaseOrderRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 采购收货。将采购单状态更新为 received。"""
    from app.models.purchase import PurchaseOrder

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "warehouse", "purchase")

    po = await db.get(PurchaseOrder, body.po_id)
    if not po:
        raise HTTPException(404, f"采购单 {body.po_id} 不存在")
    if po.status not in ("approved", "shipped"):
        raise HTTPException(400, f"采购单状态为 {po.status}，只有 approved/shipped 可收货")

    po.status = "received"
    await db.flush()
    await log_audit(db, action="receive_purchase_order", entity_type="PurchaseOrder", entity_id=po.id, user=user)
    return {"po_id": po.id, "po_no": po.po_no, "status": po.status}


# ═══════════════════════════════════════════════════════════════════
# 32. 编辑员工信息
# ═══════════════════════════════════════════════════════════════════

class MCPUpdateEmployeeRequest(BaseModel):
    employee_id: str
    name: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    social_security: Optional[float] = None
    company_social_security: Optional[float] = None


@router.post("/update-employee")
async def mcp_update_employee(body: MCPUpdateEmployeeRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 编辑员工信息。仅更新传入的非空字段。"""
    from app.models.user import Employee

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "hr")

    emp = await db.get(Employee, body.employee_id)
    if not emp:
        raise HTTPException(404, f"员工 {body.employee_id} 不存在")

    updated_fields = []
    if body.name is not None:
        emp.name = body.name
        updated_fields.append("name")
    if body.phone is not None:
        emp.phone = body.phone
        updated_fields.append("phone")
    if body.status is not None:
        emp.status = body.status
        updated_fields.append("status")
    if body.social_security is not None:
        emp.social_security = Decimal(str(body.social_security))
        updated_fields.append("social_security")
    if body.company_social_security is not None:
        emp.company_social_security = Decimal(str(body.company_social_security))
        updated_fields.append("company_social_security")
    if not updated_fields:
        raise HTTPException(400, "至少提供一个待更新字段")

    await db.flush()
    await log_audit(db, action="update_employee", entity_type="Employee", entity_id=emp.id, user=user)
    return {"employee_id": emp.id, "name": emp.name, "updated_fields": updated_fields}


# ═══════════════════════════════════════════════════════════════════
# 33. 结算提成
# ═══════════════════════════════════════════════════════════════════

class MCPSettleCommissionRequest(BaseModel):
    commission_id: str


@router.post("/settle-commission")
async def mcp_settle_commission(body: MCPSettleCommissionRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 结算提成。将提成状态设为 settled，记录结算时间。"""
    from app.models.user import Commission

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "hr", "finance")

    commission = await db.get(Commission, body.commission_id)
    if not commission:
        raise HTTPException(404, f"提成记录 {body.commission_id} 不存在")
    if commission.status == "settled":
        raise HTTPException(400, "该提成已结算")

    commission.status = "settled"
    commission.settled_at = datetime.now(timezone.utc)
    await db.flush()
    await log_audit(db, action="settle_commission", entity_type="Commission", entity_id=commission.id, user=user)
    return {"commission_id": commission.id, "status": "settled", "settled_at": str(commission.settled_at)}
