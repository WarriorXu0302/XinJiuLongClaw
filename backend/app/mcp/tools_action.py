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
# 10.5 预览订单（不创建，只匹配政策+算价格）
# ═══════════════════════════════════════════════════════════════════

class MCPPreviewOrderRequest(BaseModel):
    customer_id: str
    salesman_id: str
    settlement_mode: str = "customer_pay"
    items: list[dict]  # [{product_id, quantity, quantity_unit}]
    policy_template_id: Optional[str] = None


@router.post("/preview-order")
async def mcp_preview_order(body: MCPPreviewOrderRequest, db: AsyncSession = Depends(get_mcp_db)):
    """预览订单：匹配政策模板 + 计算价格，不真正创建。用于建单前确认。"""
    from app.models.policy_template import PolicyTemplate
    from app.models.product import Product

    user = db.info.get("mcp_user", {})
    require_mcp_employee(user)

    # 解析商品，确定品牌+箱数
    products = []
    brand_id = None
    total_cases = 0
    for it in body.items:
        pid = it["product_id"]
        prod = await db.get(Product, pid)
        if not prod:
            prod = (await db.execute(select(Product).where(Product.code == pid))).scalar_one_or_none()
        if not prod:
            prod = (await db.execute(select(Product).where(Product.name == pid))).scalar_one_or_none()
        if not prod:
            raise HTTPException(404, f"商品 {pid} 不存在")
        if brand_id and prod.brand_id != brand_id:
            raise HTTPException(400, "所有商品必须属于同一品牌")
        brand_id = prod.brand_id
        products.append((prod, it))
        if it.get("quantity_unit", "箱") == "箱":
            total_cases += it["quantity"]

    # 匹配政策模板
    if body.policy_template_id:
        tmpl = await db.get(PolicyTemplate, body.policy_template_id)
        if not tmpl:
            tmpl = (await db.execute(select(PolicyTemplate).where(PolicyTemplate.code == body.policy_template_id))).scalar_one_or_none()
        if not tmpl or not tmpl.is_active:
            return {"matched": False, "error": "指定的政策模板不存在或已停用"}
        if tmpl.min_cases and total_cases != tmpl.min_cases:
            return {"matched": False, "error": f"政策模板要求 {tmpl.min_cases} 箱，当前 {total_cases} 箱"}
    else:
        tmpl = (await db.execute(
            select(PolicyTemplate).where(
                PolicyTemplate.brand_id == brand_id,
                PolicyTemplate.is_active == True,
                PolicyTemplate.min_cases == total_cases,
            )
        )).scalar_one_or_none()
        if not tmpl:
            return {"matched": False, "error": f"没有匹配的政策模板（品牌箱数={total_cases}）。请先创建对应箱数的政策模板"}

    guide_price = Decimal(str(tmpl.required_unit_price or 0))
    customer_price = Decimal(str(tmpl.customer_unit_price or guide_price))

    total_bottles = 0
    item_details = []
    for prod, it in products:
        bpc = prod.bottles_per_case or 6
        qty = it["quantity"]
        unit = it.get("quantity_unit", "箱")
        bottles = qty * bpc if unit == "箱" else qty
        total_bottles += bottles
        item_details.append({
            "product": prod.name, "quantity": qty, "unit": unit,
            "bottles": bottles, "bottles_per_case": bpc,
        })

    total_amount = guide_price * total_bottles
    deal_amount = customer_price * total_bottles
    policy_gap = total_amount - deal_amount

    sm = body.settlement_mode
    if sm in ("customer_pay", "employee_pay"):
        customer_paid = float(total_amount)
    elif sm == "company_pay":
        customer_paid = float(deal_amount)
    else:
        customer_paid = float(total_amount)

    # 政策福利明细
    benefits = tmpl.benefit_rules or []
    benefit_summary = []
    for b in benefits:
        benefit_summary.append({
            "type": b.get("benefit_type", ""),
            "name": b.get("name", ""),
            "quantity": b.get("quantity", 0),
            "unit_value": b.get("unit_value", 0),
            "is_material": b.get("is_material", False),
        })

    return {
        "matched": True,
        "policy_template": tmpl.name,
        "policy_template_code": tmpl.code,
        "policy_template_id": tmpl.id,
        "guide_price_per_bottle": float(guide_price),
        "customer_price_per_bottle": float(customer_price),
        "total_cases": total_cases,
        "total_bottles": total_bottles,
        "items": item_details,
        "total_amount": float(total_amount),
        "deal_amount": float(deal_amount),
        "policy_gap": float(policy_gap),
        "policy_value": float(tmpl.total_policy_value or 0),
        "policy_surplus": float((tmpl.total_policy_value or 0) - policy_gap),
        "customer_paid_amount": customer_paid,
        "settlement_mode": sm,
        "benefits": benefit_summary,
        "valid_from": str(tmpl.valid_from) if tmpl.valid_from else None,
        "valid_to": str(tmpl.valid_to) if tmpl.valid_to else None,
        "hint": "确认无误后调用 create-order 创建订单（参数一致即可）",
    }


# ═══════════════════════════════════════════════════════════════════
# 11. 创建订单
# ═══════════════════════════════════════════════════════════════════

class MCPCreateOrderRequest(BaseModel):
    customer_id: str
    salesman_id: str
    policy_template_id: Optional[str] = None  # 可选：不传则按品牌+箱数自动匹配
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
    else:
        # boss/manager 指定业务员：支持 UUID、工号、姓名查找
        from app.models.user import Employee
        emp = await db.get(Employee, body.salesman_id)
        if not emp:
            emp = (await db.execute(select(Employee).where(Employee.employee_no == body.salesman_id))).scalar_one_or_none()
        if not emp:
            emp = (await db.execute(select(Employee).where(Employee.name == body.salesman_id))).scalar_one_or_none()
        if not emp:
            raise HTTPException(404, f"业务员 {body.salesman_id} 不存在")
        body.salesman_id = emp.id

    # customer_id 支持 UUID 或 code 查找
    from app.models.customer import Customer
    cust = await db.get(Customer, body.customer_id)
    if not cust:
        cust = (await db.execute(select(Customer).where(Customer.code == body.customer_id))).scalar_one_or_none()
    if not cust:
        cust = (await db.execute(select(Customer).where(Customer.name == body.customer_id))).scalar_one_or_none()
    if not cust:
        raise HTTPException(404, f"客户 {body.customer_id} 不存在（支持 UUID/编码/名称查找）")
    body.customer_id = cust.id

    # 先解析商品，确定品牌和总箱数
    products = []
    brand_id = None
    total_cases = 0
    for it in body.items:
        pid = it["product_id"]
        prod = await db.get(Product, pid)
        if not prod:
            prod = (await db.execute(select(Product).where(Product.code == pid))).scalar_one_or_none()
        if not prod:
            prod = (await db.execute(select(Product).where(Product.name == pid))).scalar_one_or_none()
        if not prod:
            raise HTTPException(404, f"商品 {pid} 不存在（支持 UUID/编码/名称）")
        if brand_id and prod.brand_id != brand_id:
            raise HTTPException(400, "所有商品必须属于同一品牌")
        brand_id = prod.brand_id
        products.append((prod, it))
        if it.get("quantity_unit", "箱") == "箱":
            total_cases += it["quantity"]

    # 政策模板：手动指定或按品牌+箱数自动匹配
    if body.policy_template_id:
        tmpl = await db.get(PolicyTemplate, body.policy_template_id)
        if not tmpl:
            tmpl = (await db.execute(select(PolicyTemplate).where(PolicyTemplate.code == body.policy_template_id))).scalar_one_or_none()
        if not tmpl or not tmpl.is_active:
            raise HTTPException(400, "政策模板不存在或已停用")
        if tmpl.min_cases and total_cases != tmpl.min_cases:
            raise HTTPException(400, f"政策模板要求 {tmpl.min_cases} 箱，当前 {total_cases} 箱")
    else:
        tmpl = (await db.execute(
            select(PolicyTemplate).where(
                PolicyTemplate.brand_id == brand_id,
                PolicyTemplate.is_active == True,
                PolicyTemplate.min_cases == total_cases,
            )
        )).scalar_one_or_none()
        if not tmpl:
            raise HTTPException(400, f"没有匹配的政策模板（品牌={brand_id}，箱数={total_cases}）。请先创建对应箱数的政策模板")

    guide_price = Decimal(str(tmpl.required_unit_price or 0))
    customer_price = Decimal(str(body.deal_unit_price or tmpl.customer_unit_price or guide_price))

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    order = Order(
        id=str(uuid.uuid4()), order_no=f"SO-{ts}-{uuid.uuid4().hex[:6]}",
        customer_id=body.customer_id, salesman_id=body.salesman_id,
        brand_id=brand_id, settlement_mode=body.settlement_mode,
        settlement_mode_snapshot=body.settlement_mode,
        advance_payer_id=body.advance_payer_id, warehouse_id=body.warehouse_id,
        policy_template_id=tmpl.id, notes=body.notes,
    )
    total = Decimal("0")
    total_bottles = 0
    for prod, it in products:
        bpc = prod.bottles_per_case or 6
        bottles = it["quantity"] * bpc if it.get("quantity_unit", "箱") == "箱" else it["quantity"]
        order.items.append(OrderItem(
            id=str(uuid.uuid4()), order_id=order.id,
            product_id=prod.id, quantity=it["quantity"],
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

    if body.settlement_mode not in ("customer_pay", "employee_pay", "company_pay"):
        raise HTTPException(400, f"settlement_mode 必须为 customer_pay/employee_pay/company_pay，收到: {body.settlement_mode}")
    if body.settlement_mode in ("customer_pay", "employee_pay"):
        order.customer_paid_amount = total
    else:
        order.customer_paid_amount = order.deal_amount
    order.policy_receivable = order.policy_gap if body.settlement_mode != "customer_pay" else Decimal("0")

    db.add(order)
    try:
        await db.flush()
    except Exception as e:
        raise HTTPException(500, f"创建订单失败: {e}")
    await log_audit(db, action="create_order", entity_type="Order", entity_id=order.id, user=user)
    return {
        "order_no": order.order_no,
        "policy_template": tmpl.name,
        "policy_template_code": tmpl.code,
        "guide_price": float(guide_price),
        "customer_price": float(customer_price),
        "total_cases": total_cases,
        "total_bottles": total_bottles,
        "total_amount": float(total),
        "deal_amount": float(order.deal_amount),
        "policy_gap": float(order.policy_gap),
        "policy_value": float(tmpl.total_policy_value or 0),
        "policy_surplus": float(order.policy_surplus or 0),
        "customer_paid_amount": float(order.customer_paid_amount),
        "settlement_mode": order.settlement_mode,
        "status": order.status,
    }


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
    # 保存更新前的 payment_status，用于判断是否首次到达 FULLY_PAID
    prev_status = order.payment_status
    if Decimal(str(total_received)) >= target:
        order.payment_status = PaymentStatus.FULLY_PAID
    elif total_received > 0:
        order.payment_status = PaymentStatus.PARTIALLY_PAID
    await db.flush()

    # ── 订单首次全额回款 → 自动生成 Commission（与 finance.py create_receipt 逻辑一致）──
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
                # customer_pay/employee_pay → total_amount；company_pay → deal_amount
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

    # refresh customer for return info
    await db.refresh(order, ["customer"])
    return {"receipt_no": receipt.receipt_no, "order_no": order.order_no,
            "amount": float(amt),
            "customer": order.customer.name if order.customer else None,
            "total_received": float(total_received),
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
    return {"id": obj.id, "code": obj.code, "name": obj.name,
            "customer_type": obj.customer_type,
            "contact_name": obj.contact_name, "contact_phone": obj.contact_phone,
            "settlement_mode": obj.settlement_mode}


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
    # 校验员工存在（支持 UUID/工号/姓名）
    from app.models.user import Employee
    emp = await db.get(Employee, body.employee_id)
    if not emp:
        emp = (await db.execute(select(Employee).where(Employee.employee_no == body.employee_id))).scalar_one_or_none()
    if not emp:
        emp = (await db.execute(select(Employee).where(Employee.name == body.employee_id))).scalar_one_or_none()
    if not emp:
        raise HTTPException(400, f"员工 {body.employee_id} 不存在")
    body.employee_id = emp.id
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
        total_days=Decimal(str(body.total_days)), reason=body.reason or "", status="pending",
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
        status="active",
    )
    db.add(emp)
    await db.flush()
    await log_audit(db, action="create_employee", entity_type="Employee", entity_id=emp.id, user=user)
    return {"id": emp.id, "employee_no": emp.employee_no, "name": emp.name,
            "position": emp.position, "phone": emp.phone, "status": emp.status}


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
    from app.models.product import Brand
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "hr")

    # employee_id fallback: UUID → employee_no → name
    emp = await db.get(Employee, body.employee_id)
    if not emp:
        emp = (await db.execute(select(Employee).where(Employee.employee_no == body.employee_id))).scalar_one_or_none()
    if not emp:
        emp = (await db.execute(select(Employee).where(Employee.name == body.employee_id))).scalar_one_or_none()
    if not emp:
        raise HTTPException(404, f"员工 {body.employee_id} 不存在")
    body.employee_id = emp.id

    # brand_id fallback: UUID → code → name
    brand = await db.get(Brand, body.brand_id)
    if not brand:
        brand = (await db.execute(select(Brand).where(Brand.code == body.brand_id))).scalar_one_or_none()
    if not brand:
        brand = (await db.execute(select(Brand).where(Brand.name == body.brand_id))).scalar_one_or_none()
    if not brand:
        raise HTTPException(404, f"品牌 {body.brand_id} 不存在")
    body.brand_id = brand.id

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
        cust = (await db.execute(select(Customer).where(Customer.code == body.customer_id))).scalar_one_or_none()
    if not cust:
        cust = (await db.execute(select(Customer).where(Customer.name == body.customer_id))).scalar_one_or_none()
    if not cust:
        raise HTTPException(404, f"客户 {body.customer_id} 不存在")
    body.customer_id = cust.id
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
    return {"customer_id": cust.id, "name": cust.name, "contact_name": cust.contact_name,
            "contact_phone": cust.contact_phone, "settlement_mode": cust.settlement_mode,
            "updated_fields": updated_fields}


# ═══════════════════════════════════════════════════════════════════
# 23. 创建采购单
# ═══════════════════════════════════════════════════════════════════

class MCPCreatePurchaseOrderRequest(BaseModel):
    supplier_id: str
    brand_id: str
    warehouse_id: str
    items: list[dict]  # [{product_id, quantity, unit_price}]
    notes: Optional[str] = None


@router.post("/create-purchase-order")
async def mcp_create_purchase_order(body: MCPCreatePurchaseOrderRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建采购单。状态为 pending，需审批后才能执行。"""
    from app.models.purchase import PurchaseOrder, PurchaseOrderItem
    from app.models.product import Product, Supplier, Brand, Warehouse
    from datetime import datetime, timezone
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "purchase", "warehouse")

    if not body.items:
        raise HTTPException(400, "采购明细不能为空")

    # supplier_id fallback: UUID → code → name
    supplier = await db.get(Supplier, body.supplier_id)
    if not supplier:
        supplier = (await db.execute(select(Supplier).where(Supplier.code == body.supplier_id))).scalar_one_or_none()
    if not supplier:
        supplier = (await db.execute(select(Supplier).where(Supplier.name == body.supplier_id))).scalar_one_or_none()
    if not supplier:
        raise HTTPException(404, f"供应商 {body.supplier_id} 不存在")
    body.supplier_id = supplier.id

    # brand_id fallback: UUID → code → name
    brand = await db.get(Brand, body.brand_id)
    if not brand:
        brand = (await db.execute(select(Brand).where(Brand.code == body.brand_id))).scalar_one_or_none()
    if not brand:
        brand = (await db.execute(select(Brand).where(Brand.name == body.brand_id))).scalar_one_or_none()
    if not brand:
        raise HTTPException(404, f"品牌 {body.brand_id} 不存在")
    body.brand_id = brand.id

    # warehouse_id fallback: UUID → code → name
    wh = await db.get(Warehouse, body.warehouse_id)
    if not wh:
        wh = (await db.execute(select(Warehouse).where(Warehouse.code == body.warehouse_id))).scalar_one_or_none()
    if not wh:
        wh = (await db.execute(select(Warehouse).where(Warehouse.name == body.warehouse_id))).scalar_one_or_none()
    if not wh:
        raise HTTPException(404, f"仓库 {body.warehouse_id} 不存在")
    body.warehouse_id = wh.id

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
    for idx, it in enumerate(body.items):
        price = Decimal(str(it["unit_price"]))
        qty = it["quantity"]
        if qty <= 0:
            raise HTTPException(400, f"第 {idx+1} 项数量必须大于 0")
        if price <= 0:
            raise HTTPException(400, f"第 {idx+1} 项单价必须大于 0")
        # product_id fallback: UUID → code → name
        pid = it["product_id"]
        prod = await db.get(Product, pid)
        if not prod:
            prod = (await db.execute(select(Product).where(Product.code == pid))).scalar_one_or_none()
        if not prod:
            prod = (await db.execute(select(Product).where(Product.name == pid))).scalar_one_or_none()
        if not prod:
            raise HTTPException(404, f"商品 {pid} 不存在（第 {idx+1} 项）")
        total += price * qty
        po.items.append(PurchaseOrderItem(
            id=str(uuid.uuid4()),
            po_id=po.id,
            product_id=prod.id,
            quantity=qty,
            quantity_unit=it.get("quantity_unit", "箱"),
            unit_price=price,
        ))
    po.total_amount = total
    db.add(po)
    await db.flush()
    await log_audit(db, action="create_purchase_order", entity_type="PurchaseOrder", entity_id=po.id, user=user)
    return {"po_no": po.po_no, "supplier": supplier.name, "warehouse": wh.name,
            "total_amount": float(total), "items_count": len(body.items), "status": po.status}


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
    from app.models.product import Brand
    from datetime import datetime, timezone
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    if body.amount <= 0:
        raise HTTPException(400, "金额必须大于 0")

    # brand_id fallback: UUID → code → name
    brand = await db.get(Brand, body.brand_id)
    if not brand:
        brand = (await db.execute(select(Brand).where(Brand.code == body.brand_id))).scalar_one_or_none()
    if not brand:
        brand = (await db.execute(select(Brand).where(Brand.name == body.brand_id))).scalar_one_or_none()
    if not brand:
        raise HTTPException(404, f"品牌 {body.brand_id} 不存在")
    body.brand_id = brand.id

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
    return {"claim_no": claim.claim_no, "amount": float(claim.amount), "status": claim.status,
            "brand": brand.name, "category": body.category, "description": body.description}


# ═══════════════════════════════════════════════════════════════════
# 25. 创建稽查案件
# ═══════════════════════════════════════════════════════════════════

class MCPCreateInspectionCaseRequest(BaseModel):
    brand_id: str
    case_type: str  # outflow_malicious / outflow_nonmalicious / outflow_transfer / inflow_resell / inflow_transfer
    direction: str  # outflow / inflow
    product_id: Optional[str] = None
    quantity: Optional[int] = None
    quantity_unit: Optional[str] = "瓶"
    deal_unit_price: Optional[float] = None  # 到手价（A1用）
    purchase_price: Optional[float] = None   # 回收价/买入价
    sale_price: Optional[float] = None       # 指导价
    resell_price: Optional[float] = None     # 回售价（B1用）
    penalty_amount: Optional[float] = None
    reward_amount: Optional[float] = None    # 奖励（B类用）
    notes: Optional[str] = None


@router.post("/create-inspection-case")
async def mcp_create_inspection_case(body: MCPCreateInspectionCaseRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建稽查案件。按 case_type 自动计算 profit_loss：
    A1 outflow_malicious: -(回收价-到手价)×瓶-罚款
    A2 outflow_nonmalicious: (指导价-回收价)×瓶-罚款
    A3 outflow_transfer: -罚款
    B1 inflow_resell: (回售价-买入价)×瓶+奖励
    B2 inflow_transfer: (指导价-买入价)×瓶+奖励
    """
    from app.models.inspection import InspectionCase
    from app.models.product import Brand, Product
    from datetime import datetime, timezone
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    # brand_id fallback: UUID → code → name
    brand = await db.get(Brand, body.brand_id)
    if not brand:
        brand = (await db.execute(select(Brand).where(Brand.code == body.brand_id))).scalar_one_or_none()
    if not brand:
        brand = (await db.execute(select(Brand).where(Brand.name == body.brand_id))).scalar_one_or_none()
    if not brand:
        raise HTTPException(404, f"品牌 {body.brand_id} 不存在")
    body.brand_id = brand.id

    # product_id fallback: UUID → code → name (if provided)
    if body.product_id:
        prod = await db.get(Product, body.product_id)
        if not prod:
            prod = (await db.execute(select(Product).where(Product.code == body.product_id))).scalar_one_or_none()
        if not prod:
            prod = (await db.execute(select(Product).where(Product.name == body.product_id))).scalar_one_or_none()
        if not prod:
            raise HTTPException(404, f"商品 {body.product_id} 不存在")
        body.product_id = prod.id

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    qty = body.quantity or 0
    bottles = qty
    if body.quantity_unit == "箱" and body.product_id:
        prod = await db.get(Product, body.product_id)
        bpc = prod.bottles_per_case if prod and prod.bottles_per_case else 1
        bottles = qty * bpc

    sale_p = Decimal(str(body.sale_price or 0))
    deal_p = Decimal(str(body.deal_unit_price or 0)) or sale_p
    purchase_p = Decimal(str(body.purchase_price or 0))
    resell_p = Decimal(str(body.resell_price or 0))
    penalty = Decimal(str(body.penalty_amount or 0))
    reward = Decimal(str(body.reward_amount or 0))
    b = Decimal(bottles)

    t = body.case_type
    if t == "outflow_malicious":
        profit_loss = -(purchase_p - deal_p) * b - penalty
    elif t == "outflow_nonmalicious":
        profit_loss = (sale_p - purchase_p) * b - penalty
    elif t == "outflow_transfer":
        profit_loss = -penalty
    elif t == "inflow_resell":
        profit_loss = (resell_p - purchase_p) * b + reward
    elif t == "inflow_transfer":
        profit_loss = (sale_p - purchase_p) * b + reward
    else:
        profit_loss = Decimal("0")

    case = InspectionCase(
        id=str(uuid.uuid4()),
        case_no=f"IC-{ts}-{uuid.uuid4().hex[:6]}",
        brand_id=body.brand_id,
        case_type=body.case_type,
        direction=body.direction,
        product_id=body.product_id,
        quantity=qty,
        quantity_unit=body.quantity_unit or "瓶",
        deal_unit_price=deal_p,
        purchase_price=purchase_p,
        original_sale_price=sale_p,
        resell_price=resell_p,
        penalty_amount=penalty,
        reward_amount=reward,
        profit_loss=profit_loss,
        notes=body.notes,
        status="pending",
    )
    db.add(case)
    await db.flush()
    await log_audit(db, action="create_inspection_case", entity_type="InspectionCase", entity_id=case.id, user=user)
    return {
        "case_no": case.case_no, "direction": case.direction,
        "case_type": case.case_type, "quantity": qty,
        "quantity_unit": body.quantity_unit or "瓶",
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

    # brand_id fallback: UUID → code → name (if provided)
    if body.brand_id:
        from app.models.product import Brand
        brand = await db.get(Brand, body.brand_id)
        if not brand:
            brand = (await db.execute(select(Brand).where(Brand.code == body.brand_id))).scalar_one_or_none()
        if not brand:
            brand = (await db.execute(select(Brand).where(Brand.name == body.brand_id))).scalar_one_or_none()
        if not brand:
            raise HTTPException(404, f"品牌 {body.brand_id} 不存在")
        body.brand_id = brand.id

    # employee_id fallback: UUID → employee_no → name (if provided)
    if body.employee_id:
        from app.models.user import Employee
        emp = await db.get(Employee, body.employee_id)
        if not emp:
            emp = (await db.execute(select(Employee).where(Employee.employee_no == body.employee_id))).scalar_one_or_none()
        if not emp:
            emp = (await db.execute(select(Employee).where(Employee.name == body.employee_id))).scalar_one_or_none()
        if not emp:
            raise HTTPException(404, f"员工 {body.employee_id} 不存在")
        body.employee_id = emp.id

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
    # Resolve human-readable names for return
    brand_name = brand.name if body.brand_id and brand else None
    emp_name = emp.name if body.employee_id and emp else None
    return {
        "target_id": target.id, "level": target.target_level,
        "target_year": target.target_year, "target_month": target.target_month,
        "brand": brand_name, "employee": emp_name,
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
        order = (await db.execute(select(Order).where(Order.order_no == body.order_id))).scalar_one_or_none()
    if not order:
        raise HTTPException(404, f"订单 {body.order_id} 不存在")

    now = datetime.now(timezone.utc)
    action = body.action

    if action == "ship":
        # 发货：approved → shipped（与 orders.py ship_order 逻辑一致）
        if order.status != OrderStatus.APPROVED:
            raise HTTPException(400, f"订单状态为 {order.status}，需要 approved 才能发货")
        # ── 政策审批校验：必须有已审批的政策申请才能出库 ──
        from app.models.policy import PolicyRequest
        policy_req = (await db.execute(
            select(PolicyRequest).where(
                PolicyRequest.order_id == order.id,
                PolicyRequest.status == "approved",
            )
        )).scalar_one_or_none()
        if not policy_req:
            raise HTTPException(400, f"无法出库：订单 {order.order_no} 没有已审批的政策申请，请先提交政策审批")
        order.status = OrderStatus.SHIPPED
        order.shipped_at = now
    elif action == "confirm-delivery":
        # 确认送达：shipped → delivered（与 orders.py confirm_delivery 逻辑一致）
        if order.status != OrderStatus.SHIPPED:
            raise HTTPException(400, f"订单状态为 {order.status}，需要 shipped 才能确认送达")
        order.status = OrderStatus.DELIVERED
        order.delivered_at = now
        # ── 为信用客户自动生成应收（与 orders.py _ensure_order_receivable 逻辑一致）──
        from app.models.customer import Customer, Receivable
        from app.models.base import CustomerSettlementMode
        from datetime import date, timedelta
        customer = await db.get(Customer, order.customer_id) if order.customer_id else None
        if customer and customer.settlement_mode == CustomerSettlementMode.CREDIT:
            existing_ar = (await db.execute(
                select(Receivable).where(Receivable.order_id == order.id)
            )).scalar_one_or_none()
            if not existing_ar:
                due = date.today() + timedelta(days=int(customer.credit_days or 0))
                ar_amount = order.customer_paid_amount if order.customer_paid_amount else order.total_amount
                if ar_amount and ar_amount > 0:
                    ar_ts = now.strftime("%Y%m%d%H%M%S")
                    db.add(Receivable(
                        id=str(uuid.uuid4()),
                        receivable_no=f"AR-{ar_ts}-{uuid.uuid4().hex[:6]}",
                        customer_id=customer.id,
                        order_id=order.id,
                        brand_id=order.brand_id,
                        amount=float(ar_amount),
                        due_date=due,
                    ))
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
    await db.refresh(order, ["customer"])
    return {"order_id": order.id, "order_no": order.order_no, "status": order.status,
            "customer": order.customer.name if order.customer else None,
            "total_amount": float(order.total_amount) if order.total_amount else 0}


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
    from app.models.product import Account, Brand
    from app.api.routes.accounts import record_fund_flow
    from datetime import date

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    if body.amount <= 0:
        raise HTTPException(400, "融资金额必须大于 0")

    # brand_id fallback: UUID → code → name
    brand = await db.get(Brand, body.brand_id)
    if not brand:
        brand = (await db.execute(select(Brand).where(Brand.code == body.brand_id))).scalar_one_or_none()
    if not brand:
        brand = (await db.execute(select(Brand).where(Brand.name == body.brand_id))).scalar_one_or_none()
    if not brand:
        raise HTTPException(404, f"品牌 {body.brand_id} 不存在")
    body.brand_id = brand.id

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

class MCPReceivePurchaseOrderRequest(BaseModel):
    po_id: str
    received_items: list[dict] = []  # [{product_id, received_quantity}]


@router.post("/receive-purchase-order")
async def mcp_receive_purchase_order(body: MCPReceivePurchaseOrderRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 采购收货。将采购单状态更新为 received。"""
    from app.models.purchase import PurchaseOrder

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "warehouse", "purchase")

    po = await db.get(PurchaseOrder, body.po_id)
    if not po:
        po = (await db.execute(select(PurchaseOrder).where(PurchaseOrder.po_no == body.po_id))).scalar_one_or_none()
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

    # employee_id fallback: UUID → employee_no → name
    emp = await db.get(Employee, body.employee_id)
    if not emp:
        emp = (await db.execute(select(Employee).where(Employee.employee_no == body.employee_id))).scalar_one_or_none()
    if not emp:
        emp = (await db.execute(select(Employee).where(Employee.name == body.employee_id))).scalar_one_or_none()
    if not emp:
        raise HTTPException(404, f"员工 {body.employee_id} 不存在")
    body.employee_id = emp.id

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


# ═══════════════════════════════════════════════════════════════════
# 32. 创建政策模板
# ═══════════════════════════════════════════════════════════════════

class MCPCreatePolicyTemplateRequest(BaseModel):
    code: str
    name: str
    brand_id: str
    template_type: str = "channel"  # channel / group_purchase
    required_unit_price: float = 0  # 指导价（进货价）
    customer_unit_price: float = 0  # 客户到手价
    min_cases: Optional[int] = None
    max_cases: Optional[int] = None
    total_policy_value: float = 0  # 政策总价值
    valid_from: Optional[str] = None  # YYYY-MM-DD
    valid_to: Optional[str] = None
    notes: Optional[str] = None


@router.post("/create-policy-template")
async def mcp_create_policy_template(body: MCPCreatePolicyTemplateRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建政策模板。建单时需要 policy_template_id。"""
    from app.models.policy_template import PolicyTemplate
    from datetime import date
    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    existing = (await db.execute(select(PolicyTemplate).where(PolicyTemplate.code == body.code))).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"政策模板编码 {body.code} 已存在")

    tmpl = PolicyTemplate(
        id=str(uuid.uuid4()),
        code=body.code,
        name=body.name,
        brand_id=body.brand_id,
        template_type=body.template_type,
        required_unit_price=Decimal(str(body.required_unit_price)),
        customer_unit_price=Decimal(str(body.customer_unit_price)),
        min_cases=body.min_cases,
        max_cases=body.max_cases,
        total_policy_value=Decimal(str(body.total_policy_value)),
        valid_from=date.fromisoformat(body.valid_from) if body.valid_from else None,
        valid_to=date.fromisoformat(body.valid_to) if body.valid_to else None,
        notes=body.notes,
    )
    db.add(tmpl)
    await db.flush()
    await log_audit(db, action="create_policy_template", entity_type="PolicyTemplate", entity_id=tmpl.id, user=user)
    return {
        "id": tmpl.id, "code": tmpl.code, "name": tmpl.name,
        "brand_id": tmpl.brand_id, "min_cases": tmpl.min_cases,
        "required_unit_price": float(tmpl.required_unit_price),
        "customer_unit_price": float(tmpl.customer_unit_price),
        "total_policy_value": float(tmpl.total_policy_value),
    }


# ═══════════════════════════════════════════════════════════════════
# 35. 发放工资
# ═══════════════════════════════════════════════════════════════════

class MCPPaySalaryRequest(BaseModel):
    salary_record_id: Optional[str] = None
    batch_mode: bool = False
    period: Optional[str] = None  # YYYY-MM, required when batch_mode=True


@router.post("/pay-salary")
async def mcp_pay_salary(body: MCPPaySalaryRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 发放工资。单条或批量（按月份批量发放所有已审批工资单）。
    完整执行（与 payroll.py pay_salary / batch_pay_salary 一致）：
    1. 从员工主属品牌现金账户扣款
    2. 记录资金流水
    3. 升级/补建厂家补贴应收为 advanced
    """
    from app.models.payroll import SalaryRecord, EmployeeBrandPosition, ManufacturerSalarySubsidy
    from app.models.product import Account
    from app.api.routes.accounts import record_fund_flow
    from datetime import datetime, timezone

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    now = datetime.now(timezone.utc)
    paid_count = 0
    total_paid = Decimal("0")

    async def _pay_single_record(rec: SalaryRecord) -> None:
        """执行单条工资发放的完整逻辑"""
        nonlocal paid_count, total_paid
        if rec.actual_pay is None or rec.actual_pay <= 0:
            rec.status = "paid"
            rec.paid_at = now
            rec.paid_by = user.get("employee_id")
            paid_count += 1
            return

        # 找员工主属品牌现金账户进行扣款
        primary_ebp = (await db.execute(
            select(EmployeeBrandPosition).where(
                EmployeeBrandPosition.employee_id == rec.employee_id,
                EmployeeBrandPosition.is_primary == True,
            )
        )).scalar_one_or_none()
        if primary_ebp:
            cash_acc = (await db.execute(
                select(Account).where(
                    Account.brand_id == primary_ebp.brand_id,
                    Account.account_type == 'cash',
                    Account.level == 'project',
                )
            )).scalar_one_or_none()
            if cash_acc:
                if cash_acc.balance < rec.actual_pay:
                    raise HTTPException(400,
                        f"品牌现金账户余额不足：{cash_acc.name} 余额 ¥{cash_acc.balance}，需付 ¥{rec.actual_pay}")
                cash_acc.balance -= rec.actual_pay
                emp_name = rec.employee.name if rec.employee else rec.employee_id[:8]
                await record_fund_flow(
                    db, account_id=cash_acc.id, flow_type='debit',
                    amount=rec.actual_pay, balance_after=cash_acc.balance,
                    related_type='salary_payment', related_id=rec.id,
                    notes=f"工资发放 {emp_name} {rec.period}",
                    created_by=user.get("employee_id"),
                    brand_id=primary_ebp.brand_id,
                )

        # 升级/补建厂家补贴应收
        ebps_with_subsidy = (await db.execute(
            select(EmployeeBrandPosition).where(
                EmployeeBrandPosition.employee_id == rec.employee_id,
                EmployeeBrandPosition.manufacturer_subsidy > 0,
            )
        )).scalars().all()
        for ebp in ebps_with_subsidy:
            existing = (await db.execute(
                select(ManufacturerSalarySubsidy).where(
                    ManufacturerSalarySubsidy.employee_id == rec.employee_id,
                    ManufacturerSalarySubsidy.brand_id == ebp.brand_id,
                    ManufacturerSalarySubsidy.period == rec.period,
                )
            )).scalar_one_or_none()
            if existing:
                if existing.status == 'pending':
                    existing.status = 'advanced'
                    existing.advanced_at = now
                    existing.salary_record_id = rec.id
                    existing.subsidy_amount = ebp.manufacturer_subsidy
            else:
                db.add(ManufacturerSalarySubsidy(
                    id=str(uuid.uuid4()),
                    employee_id=rec.employee_id,
                    brand_id=ebp.brand_id,
                    salary_record_id=rec.id,
                    period=rec.period,
                    subsidy_amount=ebp.manufacturer_subsidy,
                    status='advanced',
                    advanced_at=now,
                ))

        rec.status = "paid"
        rec.paid_at = now
        rec.paid_by = user.get("employee_id")
        paid_count += 1
        total_paid += Decimal(str(rec.actual_pay))

    if body.batch_mode:
        # 批量模式：按月份发放所有 approved 的工资单
        if not body.period:
            raise HTTPException(400, "batch_mode=True 时必须提供 period (YYYY-MM)")
        records = (await db.execute(
            select(SalaryRecord).where(
                SalaryRecord.period == body.period,
                SalaryRecord.status == "approved",
            )
        )).scalars().all()
        if not records:
            raise HTTPException(400, f"{body.period} 没有待发放（approved）的工资单")
        for rec in records:
            await _pay_single_record(rec)
    else:
        # 单条模式
        if not body.salary_record_id:
            raise HTTPException(400, "非批量模式必须提供 salary_record_id")
        rec = await db.get(SalaryRecord, body.salary_record_id)
        if not rec:
            raise HTTPException(404, f"工资单 {body.salary_record_id} 不存在")
        if rec.status != "approved":
            raise HTTPException(400, f"工资单状态为 {rec.status}，需要 approved 才能发放")
        await _pay_single_record(rec)

    await db.flush()
    await log_audit(db, action="pay_salary", entity_type="SalaryRecord",
                    entity_id=body.salary_record_id or f"batch:{body.period}", user=user)
    result = {"paid_count": paid_count, "period": body.period, "total_paid": float(total_paid)}
    if not body.batch_mode and rec:
        await db.refresh(rec, ["employee"])
        result["employee_name"] = rec.employee.name if rec.employee else None
        result["actual_pay"] = float(rec.actual_pay) if rec.actual_pay else 0
    return result


# ═══════════════════════════════════════════════════════════════════
# 36. 批量提交工资审批
# ═══════════════════════════════════════════════════════════════════

class MCPBatchSubmitSalaryRequest(BaseModel):
    period: str  # YYYY-MM


@router.post("/batch-submit-salary")
async def mcp_batch_submit_salary(body: MCPBatchSubmitSalaryRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 批量提交工资审批。将指定月份所有 draft 工资单提交为 pending_approval。"""
    from app.models.payroll import SalaryRecord
    from datetime import datetime, timezone

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "hr")

    now = datetime.now(timezone.utc)
    records = (await db.execute(
        select(SalaryRecord).where(
            SalaryRecord.period == body.period,
            SalaryRecord.status == "draft",
        )
    )).scalars().all()
    if not records:
        raise HTTPException(400, f"{body.period} 没有 draft 状态的工资单")

    for rec in records:
        rec.status = "pending_approval"
        rec.submitted_at = now
        rec.submitted_by = user.get("employee_id")
    await db.flush()
    await log_audit(db, action="batch_submit_salary", entity_type="SalaryRecord",
                    entity_id=f"batch:{body.period}", user=user)
    return {"submitted_count": len(records), "period": body.period}


# ═══════════════════════════════════════════════════════════════════
# 37. 创建/更新薪酬方案
# ═══════════════════════════════════════════════════════════════════

class MCPCreateSalarySchemeRequest(BaseModel):
    brand_id: Optional[str] = None  # null = 公司通用
    position_code: str
    fixed_salary: float = 3000
    variable_salary_max: float = 1500
    attendance_bonus_full: float = 200
    commission_rate: float = 0
    manager_share_rate: float = 0
    notes: Optional[str] = None


@router.post("/create-salary-scheme")
async def mcp_create_salary_scheme(body: MCPCreateSalarySchemeRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建或更新薪酬方案（品牌×岗位）。如果 brand_id+position_code 已存在则更新。"""
    from app.models.payroll import BrandSalaryScheme

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "hr")

    # 查是否已存在（upsert）
    stmt = select(BrandSalaryScheme).where(
        BrandSalaryScheme.position_code == body.position_code,
    )
    if body.brand_id:
        stmt = stmt.where(BrandSalaryScheme.brand_id == body.brand_id)
    else:
        stmt = stmt.where(BrandSalaryScheme.brand_id.is_(None))
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        # 更新
        existing.fixed_salary = Decimal(str(body.fixed_salary))
        existing.variable_salary_max = Decimal(str(body.variable_salary_max))
        existing.attendance_bonus_full = Decimal(str(body.attendance_bonus_full))
        existing.commission_rate = Decimal(str(body.commission_rate))
        existing.manager_share_rate = Decimal(str(body.manager_share_rate))
        if body.notes is not None:
            existing.notes = body.notes
        await db.flush()
        await log_audit(db, action="update_salary_scheme", entity_type="BrandSalaryScheme",
                        entity_id=existing.id, user=user)
        return {"id": existing.id, "action": "updated", "position_code": body.position_code}
    else:
        # 创建
        scheme = BrandSalaryScheme(
            id=str(uuid.uuid4()),
            brand_id=body.brand_id,
            position_code=body.position_code,
            fixed_salary=Decimal(str(body.fixed_salary)),
            variable_salary_max=Decimal(str(body.variable_salary_max)),
            attendance_bonus_full=Decimal(str(body.attendance_bonus_full)),
            commission_rate=Decimal(str(body.commission_rate)),
            manager_share_rate=Decimal(str(body.manager_share_rate)),
            notes=body.notes,
        )
        db.add(scheme)
        await db.flush()
        await log_audit(db, action="create_salary_scheme", entity_type="BrandSalaryScheme",
                        entity_id=scheme.id, user=user)
        return {"id": scheme.id, "action": "created", "position_code": body.position_code}


# ═══════════════════════════════════════════════════════════════════
# 38. 确认厂家工资补贴到账
# ═══════════════════════════════════════════════════════════════════

class MCPConfirmSubsidyArrivalRequest(BaseModel):
    subsidy_ids: list[str]
    arrival_billcode: Optional[str] = None


@router.post("/confirm-subsidy-arrival")
async def mcp_confirm_subsidy_arrival(body: MCPConfirmSubsidyArrivalRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 确认厂家工资补贴到账。将补贴状态设为 reimbursed 并记录到账信息。"""
    from app.models.payroll import ManufacturerSalarySubsidy
    from datetime import datetime, timezone

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    if not body.subsidy_ids:
        raise HTTPException(400, "subsidy_ids 不能为空")

    now = datetime.now(timezone.utc)
    confirmed_count = 0
    for sid in body.subsidy_ids:
        subsidy = await db.get(ManufacturerSalarySubsidy, sid)
        if not subsidy:
            raise HTTPException(404, f"补贴记录 {sid} 不存在")
        if subsidy.status == "reimbursed":
            continue  # 已到账，跳过
        subsidy.status = "reimbursed"
        subsidy.arrival_at = now
        subsidy.reimbursed_at = now
        if body.arrival_billcode:
            subsidy.arrival_billcode = body.arrival_billcode
        confirmed_count += 1

    await db.flush()
    await log_audit(db, action="confirm_subsidy_arrival", entity_type="ManufacturerSalarySubsidy",
                    entity_id=",".join(body.subsidy_ids[:5]), user=user)
    return {"confirmed_count": confirmed_count, "total_requested": len(body.subsidy_ids)}


# ═══════════════════════════════════════════════════════════════════
# 39. 政策物料兑付
# ═══════════════════════════════════════════════════════════════════

class MCPFulfillPolicyMaterialsRequest(BaseModel):
    request_id: str
    items: list[dict]  # [{item_id, fulfilled_quantity}]


@router.post("/fulfill-policy-materials")
async def mcp_fulfill_policy_materials(body: MCPFulfillPolicyMaterialsRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 更新政策物料兑付数量。逐条更新 PolicyRequestItem 的 fulfilled_qty。"""
    from app.models.policy import PolicyRequest
    from app.models.policy_request_item import PolicyRequestItem
    from datetime import datetime, timezone

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    pr = await db.get(PolicyRequest, body.request_id)
    if not pr:
        raise HTTPException(404, f"政策申请 {body.request_id} 不存在")

    if not body.items:
        raise HTTPException(400, "items 不能为空")

    now = datetime.now(timezone.utc)
    updated_count = 0
    for it in body.items:
        item_id = it.get("item_id")
        fulfilled_quantity = it.get("fulfilled_quantity", 0)
        if not item_id:
            raise HTTPException(400, "每个 item 必须包含 item_id")
        item = await db.get(PolicyRequestItem, item_id)
        if not item:
            raise HTTPException(404, f"政策项 {item_id} 不存在")
        if item.policy_request_id != body.request_id:
            raise HTTPException(400, f"政策项 {item_id} 不属于政策申请 {body.request_id}")
        item.fulfilled_qty = fulfilled_quantity
        if fulfilled_quantity >= item.quantity:
            item.fulfill_status = "fulfilled"
            item.fulfilled_at = now
        elif fulfilled_quantity > 0:
            item.fulfill_status = "applied"
        updated_count += 1

    # 检查所有 item 是否全部兑付完成
    all_items = (await db.execute(
        select(PolicyRequestItem).where(PolicyRequestItem.policy_request_id == body.request_id)
    )).scalars().all()
    all_fulfilled = all(i.fulfilled_qty >= i.quantity for i in all_items)

    # 如果所有 item 都已兑付，更新父 PolicyRequest 状态
    if all_fulfilled:
        from app.models.base import PolicyRequestStatus
        if pr.status not in (PolicyRequestStatus.APPROVED, "completed"):
            pr.status = PolicyRequestStatus.APPROVED

    await db.flush()
    await log_audit(db, action="fulfill_policy_materials", entity_type="PolicyRequest",
                    entity_id=body.request_id, user=user)
    return {
        "updated_count": updated_count,
        "all_fulfilled": all_fulfilled,
        "request_id": body.request_id,
    }


# ═══════════════════════════════════════════════════════════════════
# 40. 确认政策到账
# ═══════════════════════════════════════════════════════════════════

class MCPConfirmPolicyArrivalRequest(BaseModel):
    request_id: str


@router.post("/confirm-policy-arrival")
async def mcp_confirm_policy_arrival(body: MCPConfirmPolicyArrivalRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 确认政策到账。将政策申请状态设为 approved（已到账确认）。"""
    from app.models.policy import PolicyRequest
    from app.models.base import PolicyRequestStatus
    from datetime import datetime, timezone

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    pr = await db.get(PolicyRequest, body.request_id)
    if not pr:
        raise HTTPException(404, f"政策申请 {body.request_id} 不存在")
    if pr.status == PolicyRequestStatus.APPROVED:
        raise HTTPException(400, "该政策申请已确认到账")

    now = datetime.now(timezone.utc)
    pr.status = PolicyRequestStatus.APPROVED
    pr.updated_at = now

    await db.flush()
    await log_audit(db, action="confirm_policy_arrival", entity_type="PolicyRequest",
                    entity_id=pr.id, user=user)
    return {"request_id": pr.id, "status": pr.status}


# ═══════════════════════════════════════════════════════════════════
# 41. 确认政策兑付完成
# ═══════════════════════════════════════════════════════════════════

class MCPConfirmPolicyFulfillRequest(BaseModel):
    request_id: str


@router.post("/confirm-policy-fulfill")
async def mcp_confirm_policy_fulfill(body: MCPConfirmPolicyFulfillRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 确认政策兑付完成。将政策申请状态标记为 approved（全部兑付）。
    注意：此工具标记的是政策层面的兑付确认，不同于单项物料兑付。
    """
    from app.models.policy import PolicyRequest
    from app.models.policy_request_item import PolicyRequestItem
    from app.models.base import PolicyRequestStatus
    from datetime import datetime, timezone

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    pr = await db.get(PolicyRequest, body.request_id)
    if not pr:
        raise HTTPException(404, f"政策申请 {body.request_id} 不存在")

    # 检查所有 item 的兑付状态
    all_items = (await db.execute(
        select(PolicyRequestItem).where(PolicyRequestItem.policy_request_id == body.request_id)
    )).scalars().all()
    unfulfilled = [i for i in all_items if i.fulfill_status not in ("fulfilled", "settled")]

    now = datetime.now(timezone.utc)
    pr.status = PolicyRequestStatus.APPROVED
    pr.updated_at = now
    # 同时将所有 item 标为 fulfilled（如果尚未标记）
    for item in all_items:
        if item.fulfill_status == "pending":
            item.fulfill_status = "fulfilled"
            item.fulfilled_at = now

    await db.flush()
    await log_audit(db, action="confirm_policy_fulfill", entity_type="PolicyRequest",
                    entity_id=pr.id, user=user)
    return {
        "request_id": pr.id,
        "status": pr.status,
        "total_items": len(all_items),
        "previously_unfulfilled": len(unfulfilled),
    }


# ═══════════════════════════════════════════════════════════════════
# 42. 编辑订单
# ═══════════════════════════════════════════════════════════════════

class MCPUpdateOrderRequest(BaseModel):
    order_no: str
    customer_id: Optional[str] = None
    salesman_id: Optional[str] = None
    notes: Optional[str] = None
    warehouse_id: Optional[str] = None


@router.post("/update-order")
async def mcp_update_order(body: MCPUpdateOrderRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 编辑订单。仅允许 pending 状态下修改非空字段。"""
    from app.models.order import Order
    from app.models.base import OrderStatus

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "salesman", "sales_manager")

    order = (await db.execute(select(Order).where(Order.order_no == body.order_no))).scalar_one_or_none()
    if not order:
        raise HTTPException(404, f"订单 {body.order_no} 不存在")
    if order.status != OrderStatus.PENDING:
        raise HTTPException(400, f"订单状态为 {order.status}，只有 pending 才允许编辑")

    updated_fields = []
    if body.customer_id is not None:
        order.customer_id = body.customer_id
        updated_fields.append("customer_id")
    if body.salesman_id is not None:
        order.salesman_id = body.salesman_id
        updated_fields.append("salesman_id")
    if body.notes is not None:
        order.notes = body.notes
        updated_fields.append("notes")
    if body.warehouse_id is not None:
        order.warehouse_id = body.warehouse_id
        updated_fields.append("warehouse_id")
    if not updated_fields:
        raise HTTPException(400, "至少提供一个待更新字段")

    await db.flush()
    await log_audit(db, action="update_order", entity_type="Order", entity_id=order.id, user=user)
    return {"order_no": order.order_no, "updated_fields": updated_fields}


# ═══════════════════════════════════════════════════════════════════
# 43. 提交订单政策审批
# ═══════════════════════════════════════════════════════════════════

class MCPSubmitOrderPolicyRequest(BaseModel):
    order_no: str


@router.post("/submit-order-policy")
async def mcp_submit_order_policy(body: MCPSubmitOrderPolicyRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 提交订单进入政策内部审批。pending → policy_pending_internal。"""
    from app.models.order import Order
    from app.models.base import OrderStatus

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "salesman", "sales_manager")

    order = (await db.execute(select(Order).where(Order.order_no == body.order_no))).scalar_one_or_none()
    if not order:
        raise HTTPException(404, f"订单 {body.order_no} 不存在")
    if order.status != OrderStatus.PENDING:
        raise HTTPException(400, f"订单状态为 {order.status}，需要 pending 才能提交政策审批")

    order.status = OrderStatus.POLICY_PENDING_INTERNAL
    await db.flush()
    await log_audit(db, action="submit_order_policy", entity_type="Order", entity_id=order.id, user=user)
    return {"order_no": order.order_no, "status": order.status}


# ═══════════════════════════════════════════════════════════════════
# 44. 重新提交订单（驳回后）
# ═══════════════════════════════════════════════════════════════════

class MCPResubmitOrderRequest(BaseModel):
    order_no: str


@router.post("/resubmit-order")
async def mcp_resubmit_order(body: MCPResubmitOrderRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 重新提交被驳回的订单。policy_rejected → pending。"""
    from app.models.order import Order
    from app.models.base import OrderStatus

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "salesman", "sales_manager")

    order = (await db.execute(select(Order).where(Order.order_no == body.order_no))).scalar_one_or_none()
    if not order:
        raise HTTPException(404, f"订单 {body.order_no} 不存在")
    if order.status != OrderStatus.REJECTED:
        raise HTTPException(400, f"订单状态为 {order.status}，需要 policy_rejected 才能重新提交")

    order.status = OrderStatus.PENDING
    await db.flush()
    await log_audit(db, action="resubmit_order", entity_type="Order", entity_id=order.id, user=user)
    return {"order_no": order.order_no, "status": order.status}


# ═══════════════════════════════════════════════════════════════════
# 45. 创建政策申请
# ═══════════════════════════════════════════════════════════════════

class MCPCreatePolicyRequestRequest(BaseModel):
    brand_id: str
    order_id: Optional[str] = None
    policy_template_id: Optional[str] = None
    scheme_no: Optional[str] = None
    items: list[dict] = []  # [{product_id, quantity, quantity_unit?}]


@router.post("/create-policy-request")
async def mcp_create_policy_request(body: MCPCreatePolicyRequestRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建政策申请（PolicyRequest + PolicyRequestItem）。状态 draft。"""
    from app.models.policy import PolicyRequest
    from app.models.policy_request_item import PolicyRequestItem

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance", "salesman", "sales_manager")

    if not body.items:
        raise HTTPException(400, "政策申请明细 items 不能为空，至少需要 1 项")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    request_no = f"PR-{ts}-{uuid.uuid4().hex[:6]}"

    pr = PolicyRequest(
        id=str(uuid.uuid4()),
        brand_id=body.brand_id,
        order_id=body.order_id,
        policy_template_id=body.policy_template_id,
        scheme_no=body.scheme_no,
        status="draft",
    )
    db.add(pr)
    await db.flush()

    item_count = 0
    for idx, it in enumerate(body.items):
        db.add(PolicyRequestItem(
            id=str(uuid.uuid4()),
            policy_request_id=pr.id,
            benefit_type="product",
            name=it.get("product_id", "unknown"),
            product_id=it.get("product_id"),
            quantity=it.get("quantity", 1),
            quantity_unit=it.get("quantity_unit", "箱"),
            sort_order=idx,
        ))
        item_count += 1
    await db.flush()
    await log_audit(db, action="create_policy_request", entity_type="PolicyRequest", entity_id=pr.id, user=user)
    return {"policy_request_id": pr.id, "request_no": request_no, "items_count": item_count, "status": "draft"}


# ═══════════════════════════════════════════════════════════════════
# 46. 绑定客户-品牌-业务员
# ═══════════════════════════════════════════════════════════════════

class MCPBindCustomerBrandSalesmanRequest(BaseModel):
    customer_id: str
    brand_id: str
    salesman_id: str


@router.post("/bind-customer-brand-salesman")
async def mcp_bind_customer_brand_salesman(body: MCPBindCustomerBrandSalesmanRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 绑定/更新客户×品牌×业务员关系。已存在则更新 salesman，否则新建。"""
    from app.models.customer import Customer, CustomerBrandSalesman
    from app.models.product import Brand
    from app.models.user import Employee

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "salesman", "sales_manager")

    # customer_id fallback: UUID → code → name
    cust = await db.get(Customer, body.customer_id)
    if not cust:
        cust = (await db.execute(select(Customer).where(Customer.code == body.customer_id))).scalar_one_or_none()
    if not cust:
        cust = (await db.execute(select(Customer).where(Customer.name == body.customer_id))).scalar_one_or_none()
    if not cust:
        raise HTTPException(404, f"客户 {body.customer_id} 不存在")
    body.customer_id = cust.id

    # brand_id fallback: UUID → code → name
    brand = await db.get(Brand, body.brand_id)
    if not brand:
        brand = (await db.execute(select(Brand).where(Brand.code == body.brand_id))).scalar_one_or_none()
    if not brand:
        brand = (await db.execute(select(Brand).where(Brand.name == body.brand_id))).scalar_one_or_none()
    if not brand:
        raise HTTPException(404, f"品牌 {body.brand_id} 不存在")
    body.brand_id = brand.id

    # salesman_id fallback: UUID → employee_no → name
    emp = await db.get(Employee, body.salesman_id)
    if not emp:
        emp = (await db.execute(select(Employee).where(Employee.employee_no == body.salesman_id))).scalar_one_or_none()
    if not emp:
        emp = (await db.execute(select(Employee).where(Employee.name == body.salesman_id))).scalar_one_or_none()
    if not emp:
        raise HTTPException(404, f"业务员 {body.salesman_id} 不存在")
    body.salesman_id = emp.id

    existing = (await db.execute(
        select(CustomerBrandSalesman).where(
            CustomerBrandSalesman.customer_id == body.customer_id,
            CustomerBrandSalesman.brand_id == body.brand_id,
        )
    )).scalar_one_or_none()

    if existing:
        existing.salesman_id = body.salesman_id
        await db.flush()
        await log_audit(db, action="update_customer_brand_salesman", entity_type="CustomerBrandSalesman", entity_id=existing.id, user=user)
        return {"id": existing.id, "action": "updated", "salesman_id": body.salesman_id}
    else:
        cbs = CustomerBrandSalesman(
            id=str(uuid.uuid4()),
            customer_id=body.customer_id,
            brand_id=body.brand_id,
            salesman_id=body.salesman_id,
        )
        db.add(cbs)
        await db.flush()
        await log_audit(db, action="create_customer_brand_salesman", entity_type="CustomerBrandSalesman", entity_id=cbs.id, user=user)
        return {"id": cbs.id, "action": "created", "salesman_id": body.salesman_id}


# ═══════════════════════════════════════════════════════════════════
# 47. 创建厂家结算记录
# ═══════════════════════════════════════════════════════════════════

class MCPCreateManufacturerSettlementRequest(BaseModel):
    brand_id: str
    settlement_date: str  # YYYY-MM-DD
    amount: float
    settlement_type: Optional[str] = None
    bill_no: Optional[str] = None
    notes: Optional[str] = None


@router.post("/create-manufacturer-settlement")
async def mcp_create_manufacturer_settlement(body: MCPCreateManufacturerSettlementRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建厂家结算（到账）记录。"""
    from app.models.finance import ManufacturerSettlement
    from datetime import date

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    if body.amount <= 0:
        raise HTTPException(400, "金额必须大于 0")
    try:
        s_date = date.fromisoformat(body.settlement_date)
    except ValueError:
        raise HTTPException(400, f"日期格式错误，需要 YYYY-MM-DD，收到 {body.settlement_date}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    amt = Decimal(str(body.amount))
    settlement = ManufacturerSettlement(
        id=str(uuid.uuid4()),
        settlement_no=f"MS-{ts}-{uuid.uuid4().hex[:6]}",
        brand_id=body.brand_id,
        settlement_amount=amt,
        unsettled_amount=amt,
        settlement_date=s_date,
        notes=body.notes,
        status="pending",
    )
    db.add(settlement)
    await db.flush()
    await log_audit(db, action="create_manufacturer_settlement", entity_type="ManufacturerSettlement", entity_id=settlement.id, user=user)
    return {"settlement_id": settlement.id, "settlement_no": settlement.settlement_no, "amount": float(amt), "status": "pending"}


# ═══════════════════════════════════════════════════════════════════
# 48. 提交融资还款
# ═══════════════════════════════════════════════════════════════════

class MCPSubmitFinancingRepaymentRequest(BaseModel):
    financing_order_id: str
    principal_amount: float
    payment_account_id: str
    f_class_amount: float = 0
    notes: Optional[str] = None


@router.post("/submit-financing-repayment")
async def mcp_submit_financing_repayment(body: MCPSubmitFinancingRepaymentRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 提交融资还款申请。自动计算利息，创建 pending 状态还款单。"""
    from app.models.financing import FinancingOrder, FinancingRepayment
    from datetime import date

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    fo = await db.get(FinancingOrder, body.financing_order_id)
    if not fo:
        raise HTTPException(404, f"融资单 {body.financing_order_id} 不存在")
    if fo.status != "active":
        raise HTTPException(400, f"融资单状态为 {fo.status}，需要 active")

    principal = Decimal(str(body.principal_amount))
    if principal <= 0:
        raise HTTPException(400, "还款本金必须大于 0")
    if principal > fo.outstanding_balance:
        raise HTTPException(400, f"还款本金 {principal} 超过剩余本金 {fo.outstanding_balance}")

    # 计算利息：principal * rate / 100 * days / 365
    today = date.today()
    days = (today - fo.start_date).days if today > fo.start_date else 0
    rate = fo.interest_rate or Decimal("0")
    interest = (principal * rate / Decimal("100") * Decimal(str(days)) / Decimal("365")).quantize(Decimal("0.01"))

    f_class_amt = Decimal(str(body.f_class_amount))
    total = principal + interest

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rep = FinancingRepayment(
        id=str(uuid.uuid4()),
        repayment_no=f"FR-{ts}-{uuid.uuid4().hex[:6]}",
        financing_order_id=fo.id,
        repayment_date=today,
        interest_days=days,
        principal_amount=principal,
        interest_amount=interest,
        total_amount=total,
        payment_account_id=body.payment_account_id,
        f_class_amount=f_class_amt,
        notes=body.notes,
        status="pending",
        created_by=user.get("employee_id"),
    )
    db.add(rep)
    await db.flush()
    await log_audit(db, action="submit_financing_repayment", entity_type="FinancingRepayment", entity_id=rep.id, user=user)
    return {
        "repayment_no": rep.repayment_no, "principal": float(principal),
        "interest": float(interest), "total": float(total), "status": "pending",
    }


# ═══════════════════════════════════════════════════════════════════
# 49. 创建市场清理案件
# ═══════════════════════════════════════════════════════════════════

class MCPCreateMarketCleanupCaseRequest(BaseModel):
    brand_id: str
    case_type: str
    product_id: Optional[str] = None
    quantity: Optional[int] = None
    quantity_unit: str = "瓶"
    notes: Optional[str] = None


@router.post("/create-market-cleanup-case")
async def mcp_create_market_cleanup_case(body: MCPCreateMarketCleanupCaseRequest, db: AsyncSession = Depends(get_mcp_db)):
    """AI 创建市场清理案件。状态 pending。"""
    from app.models.inspection import MarketCleanupCase

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "finance")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    case = MarketCleanupCase(
        id=str(uuid.uuid4()),
        case_no=f"MC-{ts}-{uuid.uuid4().hex[:6]}",
        brand_id=body.brand_id,
        product_id=body.product_id,
        notes=body.notes,
        status="pending",
    )
    db.add(case)
    await db.flush()
    await log_audit(db, action="create_market_cleanup_case", entity_type="MarketCleanupCase", entity_id=case.id, user=user)
    return {"case_no": case.case_no, "status": "pending"}
