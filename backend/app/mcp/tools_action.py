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
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    obj = LeaveRequest(
        id=str(uuid.uuid4()), request_no=f"LV-{ts}-{uuid.uuid4().hex[:6]}",
        employee_id=body.employee_id, leave_type=body.leave_type,
        start_date=date.fromisoformat(body.start_date), end_date=date.fromisoformat(body.end_date),
        total_days=Decimal(str(body.total_days)), reason=body.reason, status="pending",
    )
    db.add(obj)
    await db.flush()
    return {"request_no": obj.request_no, "status": "pending"}


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
