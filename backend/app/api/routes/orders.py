"""
Order API routes — CRUD + policy flow + confirm-delivery + profit.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.permissions import apply_data_scope, require_role
from app.core.security import CurrentUser
from app.models.base import ApprovalMode, CustomerSettlementMode, OrderStatus, PolicyRequestSource
from app.models.customer import Customer, Receivable
from app.models.inventory import StockOutAllocation
from app.models.order import Order, OrderItem
from app.models.policy_template import PolicyTemplate
from app.schemas.order import (
    OrderCreate,
    OrderItemCreate,
    OrderResponse,
    OrderUpdate,
)
from app.services.audit_service import log_audit
from app.services.notification_service import notify, notify_roles

router = APIRouter()


def _generate_order_no() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"SO-{ts}-{short}"


def _generate_receivable_no() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"AR-{ts}-{short}"


# ── Order build: shared between create + create-with-policy + MCP preview ───
# 前端 OrderList.tsx createMutation 的业务真相源。MCP 与 HTTP 必须走这个函数。

def _enforce_salesman_binding(body_salesman_id: Optional[str], user: dict[str, Any]) -> str:
    """salesman 身份硬绑定：非 boss/admin/sales_manager 建单必须挂到自己名下。

    HTTP + MCP 共用。历史上 /api/orders 没这层校验，salesman 能替别人建单 → 提成错配。
    """
    roles = user.get("roles") or []
    privileged = any(r in roles for r in ("admin", "boss", "sales_manager"))
    if privileged:
        if not body_salesman_id:
            raise HTTPException(400, "boss/sales_manager 建单必须指定 salesman_id")
        return body_salesman_id
    # salesman（普通）：强制绑定到当前用户 employee_id
    emp_id = user.get("employee_id")
    if not emp_id:
        raise HTTPException(400, "当前用户未绑定员工档案，无法建单")
    return emp_id


async def _resolve_brand_and_products(
    db: AsyncSession, items: list[OrderItemCreate]
) -> tuple[str, list[tuple[Any, OrderItemCreate]]]:
    """校验所有商品同品牌，返回 (brand_id, [(Product, item), ...])。

    用 select().where() 而非 db.get() — 主键直查可能跳过 RLS session 变量，
    用 select 强制走 RLS，salesman 传别品牌 product_id 会被过滤成 None → 400。
    """
    from app.models.product import Product

    brand_id = None
    resolved: list[tuple[Any, OrderItemCreate]] = []
    for it in items:
        product = (await db.execute(
            select(Product).where(Product.id == it.product_id)
        )).scalar_one_or_none()
        if not product:
            raise HTTPException(400, f"商品 {it.product_id} 不存在或不在你的品牌范围")
        if brand_id and product.brand_id != brand_id:
            raise HTTPException(400, "所有商品必须属于同一品牌")
        if brand_id is None:
            brand_id = product.brand_id
        resolved.append((product, it))
    if brand_id is None:
        raise HTTPException(400, "订单商品为空")
    return brand_id, resolved


async def _validate_customer_belongs_to_salesman(
    db: AsyncSession, customer_id: str, salesman_id: str, brand_id: str
) -> None:
    """salesman 建单/预览时：customer × brand × salesman 三元组必须在 CBS 存在。

    用 400 而非 403 —— 跟"客户不存在"合并错误消息，不暴露"客户存在但无权访问"这个信息。
    boss/admin/sales_manager 应在调用方跳过此校验。
    """
    from app.models.customer import CustomerBrandSalesman

    exists = (await db.execute(
        select(CustomerBrandSalesman.id).where(
            CustomerBrandSalesman.customer_id == customer_id,
            CustomerBrandSalesman.salesman_id == salesman_id,
            CustomerBrandSalesman.brand_id == brand_id,
        )
    )).scalar_one_or_none()
    if not exists:
        raise HTTPException(400, "客户不存在或未绑定到你名下")


async def _match_or_load_policy_template(
    db: AsyncSession,
    brand_id: str,
    total_cases: int,
    policy_template_id: Optional[str] = None,
) -> PolicyTemplate:
    """加载或匹配政策模板。业务规则与前端 /policy-templates/templates/match 一致。

    - 有 policy_template_id：校验存在+启用+箱数匹配
    - 无：按 (brand_id, is_active, min_cases == total_cases) 精确匹配
    - 任一失败直接 400
    """
    if policy_template_id:
        tmpl = await db.get(PolicyTemplate, policy_template_id)
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
            raise HTTPException(
                400,
                f"没有匹配的政策模板（品牌={brand_id}，箱数={total_cases}）。"
                f"请先创建对应箱数的政策模板，或手动指定 policy_template_id",
            )
    if tmpl.required_unit_price is None:
        raise HTTPException(400, "政策模板未配置指导价（required_unit_price）")
    if tmpl.brand_id and tmpl.brand_id != brand_id:
        raise HTTPException(400, "政策模板品牌与商品品牌不符")
    return tmpl


def _compute_order_amounts(
    tmpl: PolicyTemplate,
    resolved_products: list[tuple[Any, OrderItemCreate]],
    settlement_mode: str,
    deal_unit_price_override: Optional[Decimal] = None,
) -> dict[str, Any]:
    """计算订单所有金额字段。返回 dict 可直接 set 到 Order 或返给 preview。

    业务真相源（与 frontend/src/pages/orders/OrderList.tsx:106-112 + backend 原实现一致）：
      total_amount        = sum(guide_price × bottles)        指导价合计（公司应收基准）
      deal_amount         = sum(customer_price × bottles)     客户到手总额
      policy_gap          = total_amount - deal_amount        政策差
      policy_value        = tmpl.total_policy_value
      policy_surplus      = policy_value - policy_gap
      customer_paid_amount:
        customer_pay    → total_amount（客户全额付指导价）
        employee_pay    → total_amount（客户付到手价 + 业务员垫差）
        company_pay     → deal_amount（公司让利，只收客户那部分）
      policy_receivable:
        customer_pay    → 0
        employee_pay    → policy_gap（等厂家兑付后返业务员）
        company_pay     → policy_gap（等厂家兑付后留公司 F 类）
    """
    if settlement_mode not in ("customer_pay", "employee_pay", "company_pay"):
        raise HTTPException(
            400, f"settlement_mode 必须为 customer_pay/employee_pay/company_pay，收到: {settlement_mode}"
        )

    guide_price = Decimal(str(tmpl.required_unit_price))
    customer_price = Decimal(str(tmpl.customer_unit_price or tmpl.required_unit_price))
    if deal_unit_price_override is not None:
        customer_price = Decimal(str(deal_unit_price_override))

    total = Decimal("0")
    total_bottles = 0
    for prod, it in resolved_products:
        bpc = prod.bottles_per_case or 6
        bottles = it.quantity * bpc if it.quantity_unit == "箱" else it.quantity
        total += guide_price * bottles
        total_bottles += bottles

    deal_amount = customer_price * total_bottles
    policy_gap = total - deal_amount
    policy_value = tmpl.total_policy_value or Decimal("0")
    policy_surplus = policy_value - policy_gap

    if settlement_mode == "customer_pay":
        customer_paid_amount = total
        policy_receivable = Decimal("0")
    elif settlement_mode == "employee_pay":
        customer_paid_amount = total
        policy_receivable = policy_gap
    else:  # company_pay
        customer_paid_amount = deal_amount
        policy_receivable = policy_gap

    return {
        "guide_price": guide_price,
        "customer_price": customer_price,
        "total_bottles": total_bottles,
        "total_amount": total,
        "deal_amount": deal_amount,
        "policy_gap": policy_gap,
        "policy_value": policy_value,
        "policy_surplus": policy_surplus,
        "customer_paid_amount": customer_paid_amount,
        "policy_receivable": policy_receivable,
    }


async def _build_order_from_computed(
    db: AsyncSession,
    body: OrderCreate,
    user: dict[str, Any],
    tmpl: PolicyTemplate,
    resolved_products: list[tuple[Any, OrderItemCreate]],
    brand_id: str,
    amounts: dict[str, Any],
) -> Order:
    """用 _compute_order_amounts 的结果构造 Order + OrderItem。不 flush，由调用方决定。"""
    order = Order(
        id=str(uuid.uuid4()),
        order_no=_generate_order_no(),
        customer_id=body.customer_id,
        salesman_id=body.salesman_id,  # 已经过 _enforce_salesman_binding
        brand_id=brand_id,
        settlement_mode_snapshot=body.settlement_mode_snapshot,
        settlement_mode=body.settlement_mode,
        advance_payer_id=body.advance_payer_id,
        warehouse_id=body.warehouse_id,
        policy_template_id=tmpl.id,
        notes=body.notes,
    )

    guide_price = amounts["guide_price"]
    for prod, it in resolved_products:
        oi = OrderItem(
            id=str(uuid.uuid4()),
            order_id=order.id,
            product_id=it.product_id,
            quantity=it.quantity,
            quantity_unit=it.quantity_unit,
            unit_price=guide_price,  # 强制政策指导价，不尊重 body.items[].unit_price
        )
        order.items.append(oi)

    order.total_amount = amounts["total_amount"]
    order.deal_unit_price = amounts["customer_price"]
    order.deal_amount = amounts["deal_amount"]
    order.policy_gap = amounts["policy_gap"]
    order.policy_value = amounts["policy_value"]
    order.policy_surplus = amounts["policy_surplus"]
    order.customer_paid_amount = amounts["customer_paid_amount"]
    order.policy_receivable = amounts["policy_receivable"]

    db.add(order)
    return order


async def _ensure_order_receivable(db: AsyncSession, order: Order) -> None:
    """为已送达的信用客户订单生成应收（幂等）。
    - 若该订单已存在 Receivable，不重复生成
    - brand_id 正确赋值
    - 若订单有政策缺口且结算模式为 employee_pay/company_pay，额外生成政策应收
    """
    if not order.customer_id:
        return
    # 幂等：查是否已有 Receivable
    existing = (await db.execute(
        select(Receivable).where(Receivable.order_id == order.id)
    )).scalars().all()
    if existing:
        return
    customer = await db.get(Customer, order.customer_id)
    if not customer or customer.settlement_mode != CustomerSettlementMode.CREDIT:
        return
    due = date.today() + timedelta(days=int(customer.credit_days or 0))
    # 客户应付部分
    customer_owe = order.customer_paid_amount if order.customer_paid_amount is not None else order.total_amount
    if customer_owe and customer_owe > 0:
        db.add(Receivable(
            id=str(uuid.uuid4()),
            receivable_no=_generate_receivable_no(),
            customer_id=customer.id,
            order_id=order.id,
            brand_id=order.brand_id,
            amount=float(customer_owe),
            due_date=due,
        ))


# ── CRUD ─────────────────────────────────────────────────────────────


# ═══════════════════════════════════════════════════════════════════
# Preview — 建单前拿到指导价 / 客户到手价 / 政策差 / 公司应收
# 前端表单实时计算时用；MCP 建单前让 agent 展示给用户的金额也走这个
# ═══════════════════════════════════════════════════════════════════


class OrderPreviewRequest(BaseModel):
    items: list[OrderItemCreate]
    settlement_mode: str  # customer_pay / employee_pay / company_pay
    policy_template_id: Optional[str] = None
    deal_unit_price: Optional[Decimal] = None
    customer_id: Optional[str] = None  # 可选，若传则校验 salesman 归属


class OrderPreviewResponse(BaseModel):
    brand_id: str
    total_cases: int
    total_bottles: int
    guide_price_per_bottle: Decimal
    customer_price_per_bottle: Decimal
    total_amount: Decimal  # 指导价合计
    deal_amount: Decimal  # 到手价合计
    policy_gap: Decimal
    policy_value: Decimal
    policy_surplus: Decimal
    customer_paid_amount: Decimal  # 公司应收
    policy_receivable: Decimal
    settlement_mode: str
    policy_template_id: str
    policy_template_name: str
    policy_template_code: str


@router.post("/preview", response_model=OrderPreviewResponse)
async def preview_order(
    body: OrderPreviewRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """不持久化，只返回金额计算结果。与 POST /api/orders 同一个计算函数。

    权限：boss/salesman/sales_manager/finance。
    - finance：审批时查金额
    - salesman：只能预览自己名下客户的订单（需传 customer_id 才校验）
    """
    require_role(user, "boss", "salesman", "sales_manager", "finance")

    brand_id, resolved = await _resolve_brand_and_products(db, body.items)
    total_cases = sum(it.quantity if it.quantity_unit == "箱" else 0 for it in body.items)
    tmpl = await _match_or_load_policy_template(db, brand_id, total_cases, body.policy_template_id)
    amounts = _compute_order_amounts(tmpl, resolved, body.settlement_mode, body.deal_unit_price)

    # salesman 如果传了 customer_id 要校验归属（防通过 preview 套出别人客户的金额）
    roles = user.get("roles") or []
    is_privileged = any(r in roles for r in ("admin", "boss", "sales_manager", "finance"))
    cust_id = getattr(body, "customer_id", None)
    if not is_privileged and cust_id:
        emp_id = user.get("employee_id")
        if not emp_id:
            raise HTTPException(400, "当前用户未绑定员工档案")
        await _validate_customer_belongs_to_salesman(db, cust_id, emp_id, brand_id)

    return OrderPreviewResponse(
        brand_id=brand_id,
        total_cases=total_cases,
        total_bottles=amounts["total_bottles"],
        guide_price_per_bottle=amounts["guide_price"],
        customer_price_per_bottle=amounts["customer_price"],
        total_amount=amounts["total_amount"],
        deal_amount=amounts["deal_amount"],
        policy_gap=amounts["policy_gap"],
        policy_value=amounts["policy_value"],
        policy_surplus=amounts["policy_surplus"],
        customer_paid_amount=amounts["customer_paid_amount"],
        policy_receivable=amounts["policy_receivable"],
        settlement_mode=body.settlement_mode,
        policy_template_id=tmpl.id,
        policy_template_name=tmpl.name,
        policy_template_code=tmpl.code,
    )


@router.post("", response_model=OrderResponse, status_code=201)
async def create_order(body: OrderCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """仅建 Order — 不连带建 PolicyRequest 或 submit-policy。

    前端正常建单走 `/api/orders/create-with-policy`（合并接口，事务化）。
    此接口保留给"只建单不提审批"的老流程 / 测试用，普通调用方应改用合并接口。
    """
    require_role(user, "boss", "salesman", "sales_manager")

    # salesman 身份硬绑定：非 boss/sales_manager 不能替别人建单
    body.salesman_id = _enforce_salesman_binding(body.salesman_id, user)

    # 商品+品牌解析
    brand_id, resolved = await _resolve_brand_and_products(db, body.items)

    # 客户归属校验：salesman 只能给自己名下客户建单
    roles = user.get("roles") or []
    is_privileged = any(r in roles for r in ("admin", "boss", "sales_manager"))
    if not is_privileged and body.customer_id:
        await _validate_customer_belongs_to_salesman(
            db, body.customer_id, body.salesman_id, brand_id
        )

    # 政策匹配
    total_cases = sum(it.quantity if it.quantity_unit == "箱" else 0 for it in body.items)
    tmpl = await _match_or_load_policy_template(db, brand_id, total_cases, body.policy_template_id)

    # 金额计算
    amounts = _compute_order_amounts(tmpl, resolved, body.settlement_mode, body.deal_unit_price)

    # 构造 Order + Items
    order = await _build_order_from_computed(db, body, user, tmpl, resolved, brand_id, amounts)

    await db.flush()
    # Re-fetch with selectinload to populate customer/salesman/items.product
    refreshed = (await db.execute(
        select(Order).where(Order.id == order.id).options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.customer),
            selectinload(Order.salesman),
        )
    )).scalar_one()
    return refreshed


# ═══════════════════════════════════════════════════════════════════
# 合并接口：建单 + PolicyRequest + submit-policy 事务化一次完成
# 对齐前端 OrderList.tsx:148-228 createMutation 的三步串行动作
# 整体失败回滚，避免"孤儿 Order / 无政策申请" 状态
# ═══════════════════════════════════════════════════════════════════


class OrderCreateWithPolicyRequest(BaseModel):
    """前端 createMutation 的合并 body。"""

    # Order 部分
    customer_id: str
    salesman_id: Optional[str] = None
    items: list[OrderItemCreate]
    policy_template_id: Optional[str] = None
    settlement_mode: str  # customer_pay / employee_pay / company_pay
    deal_unit_price: Optional[Decimal] = None
    advance_payer_id: Optional[str] = None
    warehouse_id: Optional[str] = None
    notes: Optional[str] = None

    # PolicyRequest 扩展部分（微调暂未支持，approval_mode 固定 internal_only）
    # 若未来支持微调：新增 adjusted_benefit_rules 字段 → approval_mode=internal_plus_external


@router.post("/create-with-policy", response_model=OrderResponse, status_code=201)
async def create_order_with_policy(
    body: OrderCreateWithPolicyRequest, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """原子化建单：Order + PolicyRequest + OrderRequestItem[] + submit-policy（→ policy_pending_internal）。

    业务真相源：前端 frontend/src/pages/orders/OrderList.tsx:148-228 createMutation
    的三步串行动作，此接口合并为一个事务。

    三步对应：
      1) POST /api/orders                 (create Order + OrderItem)
      2) POST /api/policies/requests      (create PolicyRequest + request_items[])
      3) POST /api/orders/{id}/submit-policy  (pending → policy_pending_internal)
    """
    from app.models.policy import PolicyRequest
    from app.models.policy_request_item import PolicyRequestItem

    require_role(user, "boss", "salesman", "sales_manager")

    # ── Step 0: salesman 身份硬绑定 ───────────────────────────
    body.salesman_id = _enforce_salesman_binding(body.salesman_id, user)

    # ── Step 1: 建 Order ──────────────────────────────────────
    brand_id, resolved = await _resolve_brand_and_products(db, body.items)

    # 客户归属校验：salesman 只能给自己名下客户建单
    roles = user.get("roles") or []
    is_privileged = any(r in roles for r in ("admin", "boss", "sales_manager"))
    if not is_privileged:
        await _validate_customer_belongs_to_salesman(
            db, body.customer_id, body.salesman_id, brand_id
        )

    total_cases = sum(it.quantity if it.quantity_unit == "箱" else 0 for it in body.items)
    tmpl = await _match_or_load_policy_template(db, brand_id, total_cases, body.policy_template_id)
    amounts = _compute_order_amounts(tmpl, resolved, body.settlement_mode, body.deal_unit_price)

    # 转成 OrderCreate body 复用 _build_order_from_computed
    order_body = OrderCreate(
        customer_id=body.customer_id,
        salesman_id=body.salesman_id,
        items=body.items,
        policy_template_id=tmpl.id,
        settlement_mode=body.settlement_mode,
        advance_payer_id=body.advance_payer_id,
        warehouse_id=body.warehouse_id,
        deal_unit_price=body.deal_unit_price,
        notes=body.notes,
    )
    order = await _build_order_from_computed(db, order_body, user, tmpl, resolved, brand_id, amounts)
    await db.flush()

    # ── Step 2: 建 PolicyRequest + request_items ─────────────
    # 对应前端 OrderList.tsx:192-222
    pr = PolicyRequest(
        id=str(uuid.uuid4()),
        request_source=PolicyRequestSource.ORDER,
        approval_mode=ApprovalMode.INTERNAL_ONLY,  # 非微调固定 internal_only
        order_id=order.id,
        customer_id=body.customer_id,
        brand_id=brand_id,
        policy_id=tmpl.id,
        policy_template_id=tmpl.id,
        scheme_no=tmpl.default_scheme_no,
        total_policy_value=tmpl.total_policy_value or Decimal("0"),
        total_gap=amounts["policy_gap"],
        settlement_mode=body.settlement_mode,
        usage_purpose=f"{tmpl.name} - 标准政策",
        policy_snapshot=tmpl.benefit_rules,
    )
    db.add(pr)

    # request_items 映射：前端 OrderList.tsx:208-221 对应逻辑
    # settlement_mode → advance_payer_type 映射
    if body.settlement_mode == "customer_pay":
        payer_type = "customer"
        payer_id = None
    elif body.settlement_mode == "employee_pay":
        payer_type = "employee"
        if not body.advance_payer_id:
            raise HTTPException(400, "employee_pay 模式必须指定 advance_payer_id（垫付业务员）")
        payer_id = body.advance_payer_id
    else:  # company_pay
        payer_type = "company"
        payer_id = None

    # 从 PolicyTemplate.benefits 拷到 PolicyRequestItem
    # 重新加载 benefits 关系，确保数据完整
    tmpl_with_benefits = (await db.execute(
        select(PolicyTemplate).where(PolicyTemplate.id == tmpl.id).options(
            selectinload(PolicyTemplate.benefits)
        )
    )).scalar_one()
    for i, b in enumerate(tmpl_with_benefits.benefits or []):
        suv = Decimal(str(b.standard_unit_value or 0))
        st = suv * b.quantity
        uv = Decimal(str(b.unit_value or 0))
        tv = uv * b.quantity
        ri = PolicyRequestItem(
            id=str(uuid.uuid4()),
            policy_request_id=pr.id,
            benefit_type=b.benefit_type,
            name=b.name,
            quantity=b.quantity,
            quantity_unit=b.quantity_unit or "次",
            standard_unit_value=suv,
            standard_total=st,
            unit_value=uv,
            total_value=tv,
            product_id=b.product_id,
            is_material=b.is_material or False,
            fulfill_mode=b.fulfill_mode or ("material" if b.is_material else "claim"),
            advance_payer_type=payer_type,
            advance_payer_id=payer_id,
            sort_order=i,
        )
        pr.request_items.append(ri)

    await db.flush()

    # ── Step 3: submit-policy（pending → policy_pending_internal）──
    order.status = OrderStatus.POLICY_PENDING_INTERNAL
    await db.flush()

    # ── 审计 + 通知 ───────────────────────────────────────────
    await log_audit(db, action="create_order_with_policy", entity_type="Order", entity_id=order.id, user=user)

    # Re-fetch 带完整关系（async session 下不能 lazy-load order.customer）
    refreshed = (await db.execute(
        select(Order).where(Order.id == order.id).options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.customer),
            selectinload(Order.salesman),
        )
    )).scalar_one()

    cust_name = refreshed.customer.name if refreshed.customer else ""
    await notify_roles(
        db, role_codes=["admin", "boss"],
        title=f"新政策审批: {refreshed.order_no}",
        content=f"客户 {cust_name}，订单 {refreshed.order_no}，金额 ¥{refreshed.total_amount}，请审批",
        entity_type="Order", entity_id=refreshed.id,
    )
    return refreshed


@router.get("")
async def list_orders(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    status: str | None = Query(None),
    payment_status: str | None = Query(None),
    customer_id: str | None = Query(None),
    salesman_id: str | None = Query(None),
    keyword: str | None = Query(None, description="订单号/客户名 模糊"),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
    amount_min: float | None = Query(None),
    amount_max: float | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime as _dt
    base = select(Order)
    if brand_id:
        base = base.where(Order.brand_id == brand_id)
    if status:
        base = base.where(Order.status == status)
    if payment_status:
        base = base.where(Order.payment_status == payment_status)
    if customer_id:
        base = base.where(Order.customer_id == customer_id)
    if salesman_id:
        base = base.where(Order.salesman_id == salesman_id)
    if amount_min is not None:
        base = base.where(Order.total_amount >= amount_min)
    if amount_max is not None:
        base = base.where(Order.total_amount <= amount_max)
    if date_from:
        try:
            base = base.where(Order.created_at >= _dt.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            base = base.where(Order.created_at <= _dt.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59))
        except ValueError:
            pass
    if keyword:
        kw = f"%{keyword}%"
        base = base.outerjoin(Customer, Customer.id == Order.customer_id).where(
            (Order.order_no.ilike(kw)) | (Customer.name.ilike(kw))
        )
    base = apply_data_scope(base, user, salesman_column=Order.salesman_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(
        base.options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.customer),
            selectinload(Order.salesman),
        ).order_by(Order.created_at.desc()).offset(skip).limit(limit)
    )).scalars().all()
    return {"items": rows, "total": total}


@router.get("/pending-receipt-confirmation")
async def list_orders_pending_receipt_confirmation(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """审批中心列表：有 pending Receipt 的订单。

    **必须注册在 /{order_id} GET 之前**，否则 "pending-receipt-confirmation"
    会被当成 order_id 路径参数吃掉，返回 "Order not found"。

    finance/boss 用。每个订单聚合显示：订单基本信息 + pending 凭证笔数和累计金额。
    """
    require_role(user, "boss", "finance", "admin")
    from app.models.finance import Receipt

    pending_sub = (
        select(
            Receipt.order_id,
            func.count(Receipt.id).label("pending_count"),
            func.coalesce(func.sum(Receipt.amount), 0).label("pending_amount"),
        )
        .where(Receipt.status == "pending_confirmation")
        .group_by(Receipt.order_id)
        .subquery()
    )

    q = (
        select(Order, pending_sub.c.pending_count, pending_sub.c.pending_amount)
        .join(pending_sub, pending_sub.c.order_id == Order.id)
    )
    if brand_id:
        q = q.where(Order.brand_id == brand_id)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    rows = (await db.execute(
        q.order_by(Order.created_at.desc()).offset(skip).limit(limit)
    )).all()

    items = [
        {
            "order_id": order.id,
            "order_no": order.order_no,
            "customer_id": order.customer_id,
            "brand_id": order.brand_id,
            "salesman_id": order.salesman_id,
            "total_amount": float(order.total_amount),
            "customer_paid_amount": float(order.customer_paid_amount) if order.customer_paid_amount else None,
            "settlement_mode": order.settlement_mode,
            "pending_receipt_count": int(pending_count),
            "pending_receipt_amount": float(pending_amount),
            "payment_status": order.payment_status,
            "created_at": order.created_at.isoformat() if order.created_at else None,
        }
        for order, pending_count, pending_amount in rows
    ]
    return {"items": items, "total": total}


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(order_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    order = (await db.execute(
        select(Order).where(Order.id == order_id).options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.customer),
            selectinload(Order.salesman),
        )
    )).scalar_one_or_none()
    if order is None:
        raise HTTPException(404, "Order not found")
    return order


@router.put("/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: str, body: OrderUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    require_role(user, "boss", "salesman", "sales_manager")
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")

    data = body.model_dump(exclude_unset=True)
    items_data = data.pop("items", None)
    for k, v in data.items():
        setattr(order, k, v)

    if items_data is not None:
        # Replace items entirely — validate each through Pydantic
        order.items.clear()
        total = 0
        for it_data in items_data:
            it = OrderItemCreate(**it_data)
            oi = OrderItem(
                id=str(uuid.uuid4()),
                order_id=order.id,
                product_id=it.product_id,
                quantity=it.quantity,
                unit_price=it.unit_price,
            )
            order.items.append(oi)
            total += it.quantity * it.unit_price
        order.total_amount = total

    await db.flush()
    refreshed = (await db.execute(
        select(Order).where(Order.id == order.id).options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.customer),
            selectinload(Order.salesman),
        )
    )).scalar_one()
    return refreshed


@router.delete("/{order_id}", status_code=204)
async def delete_order(order_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss")
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    # 保护：已发货/已送达/已完成订单不能硬删，否则库存+应收成孤立记录
    if order.status in (OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.COMPLETED):
        raise HTTPException(400, f"订单状态为 {order.status}，已发货/送达/完成的订单不能删除（需走退货流程）")
    await log_audit(db, action="delete_order", entity_type="Order", entity_id=order.id,
                    changes={"order_no": order.order_no, "status": order.status}, user=user)
    await db.delete(order)
    await db.flush()


# ── Business: confirm delivery (PRD §6.1) ───────────────────────────


@router.post("/{order_id}/confirm-delivery", response_model=OrderResponse)
async def confirm_delivery(order_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Mark order as delivered.

    If the customer is a credit customer (settlement_mode='credit'),
    auto-generate a receivable record.
    """
    require_role(user, "boss", "warehouse", "salesman")
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    if order.status != OrderStatus.SHIPPED:
        raise HTTPException(
            400, f"Cannot confirm delivery for order in status '{order.status}', expected 'shipped'"
        )

    now = datetime.now(timezone.utc)
    order.status = OrderStatus.DELIVERED
    order.delivered_at = now

    await _ensure_order_receivable(db, order)

    await db.flush()
    await log_audit(db, action="confirm_delivery", entity_type="Order", entity_id=order.id, user=user)
    return order


# ── Business: ship order (PRD §3.1.2) ───────────────────────────────


@router.post("/{order_id}/ship", response_model=OrderResponse)
async def ship_order(order_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """approved → shipped (after stock-out scanning).

    Validates that a matching policy request exists for this order.
    No policy = cannot ship.
    """
    require_role(user, "boss", "warehouse", "salesman")
    from app.models.policy import PolicyRequest

    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    if order.status != OrderStatus.APPROVED:
        raise HTTPException(400, f"Cannot ship: order is in '{order.status}', expected 'approved'")

    # ── Policy validation: order must have an approved policy request ──
    policy_req = (
        await db.execute(
            select(PolicyRequest).where(
                PolicyRequest.order_id == order_id,
                PolicyRequest.status == "approved",
            )
        )
    ).scalar_one_or_none()
    if policy_req is None:
        raise HTTPException(
            400, "无法出库：该订单没有已审批的政策申请，请先创建并审批政策"
        )

    order.status = OrderStatus.SHIPPED
    order.shipped_at = datetime.now(timezone.utc)
    await db.flush()
    await log_audit(db, action="ship_order", entity_type="Order", entity_id=order.id, user=user)
    await notify_roles(
        db, role_codes=["admin", "boss", "finance"],
        title=f"订单已出库: {order.order_no}",
        content=f"订单 {order.order_no} 已扫码出库，等待送货确认",
        entity_type="Order", entity_id=order.id,
    )
    return order


# ── Business: complete order (PRD §3.1.2) ────────────────────────────


@router.post("/{order_id}/complete", response_model=OrderResponse)
async def complete_order(order_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """delivered → completed (fulfillment archived)."""
    require_role(user, "boss", "finance")
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(400, f"Cannot complete: order is in '{order.status}', expected 'delivered'")

    order.status = OrderStatus.COMPLETED
    order.completed_at = datetime.now(timezone.utc)
    await db.flush()
    await log_audit(db, action="complete_order", entity_type="Order", entity_id=order.id, user=user)
    return order


class RejectPolicyBody(BaseModel):
    rejection_reason: str


@router.post("/{order_id}/submit-policy", response_model=OrderResponse)
async def submit_for_policy(order_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """pending → policy_pending_internal"""
    require_role(user, "boss", "salesman", "sales_manager")
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    if order.status != OrderStatus.PENDING:
        raise HTTPException(400, f"Cannot submit: order is in '{order.status}', expected 'pending'")

    order.status = OrderStatus.POLICY_PENDING_INTERNAL
    await db.flush()
    await log_audit(db, action="submit_policy", entity_type="Order", entity_id=order.id, user=user)
    cust_name = order.customer.name if order.customer else ""
    await notify_roles(
        db, role_codes=["admin", "boss"],
        title=f"新政策审批: {order.order_no}",
        content=f"客户 {cust_name}，订单 {order.order_no}，金额 ¥{order.total_amount}，请审批",
        entity_type="Order", entity_id=order.id,
    )
    return order


@router.post("/{order_id}/approve-policy", response_model=OrderResponse)
async def approve_policy(
    order_id: str,
    user: CurrentUser,
    need_external: bool = Query(False, description="是否需要厂家外部审批"),
    db: AsyncSession = Depends(get_db),
):
    """policy_pending_internal → approved (or → policy_pending_external)"""
    require_role(user, "boss")
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    if order.status != OrderStatus.POLICY_PENDING_INTERNAL:
        raise HTTPException(
            400, f"Cannot approve: order is in '{order.status}', expected 'policy_pending_internal'"
        )

    if need_external:
        order.status = OrderStatus.POLICY_PENDING_EXTERNAL
    else:
        order.status = OrderStatus.APPROVED
    await db.flush()
    await log_audit(db, action="approve_policy", entity_type="Order", entity_id=order.id, user=user)
    if order.salesman_id:
        from app.models.user import User
        salesman_user = (await db.execute(
            select(User).where(User.employee_id == order.salesman_id)
        )).scalar_one_or_none()
        if salesman_user:
            await notify(
                db, recipient_id=salesman_user.id,
                title=f"政策已通过: {order.order_no}",
                content=f"订单 {order.order_no} 政策审批已通过，请扫码出库",
                entity_type="Order", entity_id=order.id,
            )
    return order


@router.post("/{order_id}/confirm-external", response_model=OrderResponse)
async def confirm_external_policy(order_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """policy_pending_external → approved"""
    require_role(user, "boss")
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    if order.status != OrderStatus.POLICY_PENDING_EXTERNAL:
        raise HTTPException(
            400, f"Cannot confirm external: order is in '{order.status}', expected 'policy_pending_external'"
        )

    order.status = OrderStatus.APPROVED
    await db.flush()
    await log_audit(db, action="confirm_external_policy", entity_type="Order", entity_id=order.id, user=user)
    return order


@router.post("/{order_id}/reject-policy", response_model=OrderResponse)
async def reject_policy(
    order_id: str, body: RejectPolicyBody, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """policy_pending_* → policy_rejected"""
    require_role(user, "boss")
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    if order.status not in (
        OrderStatus.POLICY_PENDING_INTERNAL,
        OrderStatus.POLICY_PENDING_EXTERNAL,
    ):
        raise HTTPException(400, f"Cannot reject: order is in '{order.status}'")

    order.status = OrderStatus.REJECTED
    order.rejection_reason = body.rejection_reason
    await db.flush()
    await log_audit(
        db, action="reject_policy", entity_type="Order", entity_id=order.id,
        changes={"rejection_reason": body.rejection_reason}, user=user)
    if order.salesman_id:
        from app.models.user import User
        salesman_user = (await db.execute(
            select(User).where(User.employee_id == order.salesman_id)
        )).scalar_one_or_none()
        if salesman_user:
            await notify(
                db, recipient_id=salesman_user.id,
                title=f"政策被驳回: {order.order_no}",
                content=f"订单 {order.order_no} 政策被驳回，原因: {body.rejection_reason}，请重新提交",
                entity_type="Order", entity_id=order.id,
            )
    return order


# ═══════════════════════════════════════════════════════════════════
# 政策审批合并接口：PolicyRequest.status + Order.status 一次事务内更新
# 对齐前端 PolicyApproval.tsx:72-111 approveMutation / rejectMutation 的两步串行
# ═══════════════════════════════════════════════════════════════════


@router.post("/{order_id}/approve-policy-with-request", response_model=OrderResponse)
async def approve_policy_with_request(
    order_id: str,
    user: CurrentUser,
    need_external: bool = Query(False, description="是否需要厂家外部审批"),
    db: AsyncSession = Depends(get_db),
):
    """一次批准：把 Order 关联的 PolicyRequest.status=approved + Order 推进到 approved（或 policy_pending_external）。

    对应前端 PolicyApproval.tsx:72-91 approveMutation 两步：
      1) PUT  /api/policies/requests/{prId}   (status: 'approved')
      2) POST /api/orders/{order_id}/approve-policy
    """
    from app.models.policy import PolicyRequest
    from app.models.base import PolicyRequestStatus

    require_role(user, "boss")

    # 用 select + RLS 走品牌隔离（admin 除外）。别品牌订单查不出 → 404
    order = (await db.execute(
        select(Order).where(Order.id == order_id)
    )).scalar_one_or_none()
    if order is None:
        raise HTTPException(404, "Order not found")
    # 主动校验 brand 归属（非 admin/boss 的 brand_ids 白名单）
    roles = user.get("roles") or []
    if "admin" not in roles:
        brand_ids = user.get("brand_ids") or []
        if brand_ids and order.brand_id and order.brand_id not in brand_ids:
            raise HTTPException(404, "Order not found")  # 统一用 404 不暴露存在性
    if order.status != OrderStatus.POLICY_PENDING_INTERNAL:
        raise HTTPException(
            400, f"Cannot approve: order is in '{order.status}', expected 'policy_pending_internal'"
        )

    # 找到关联的 pending_internal 状态的 PolicyRequest（通常一个订单一个 PR）
    pr = (await db.execute(
        select(PolicyRequest).where(
            PolicyRequest.order_id == order_id,
            PolicyRequest.status == PolicyRequestStatus.PENDING_INTERNAL,
        )
    )).scalar_one_or_none()

    # Step 1: 更新 PolicyRequest（如有）
    if pr:
        pr.status = PolicyRequestStatus.APPROVED
        pr.internal_approved_by = user.get("employee_id")

    # Step 2: 推进 Order 状态
    if need_external:
        order.status = OrderStatus.POLICY_PENDING_EXTERNAL
    else:
        order.status = OrderStatus.APPROVED

    await db.flush()
    await log_audit(
        db, action="approve_policy_with_request", entity_type="Order",
        entity_id=order.id, user=user,
        changes={"policy_request_id": pr.id if pr else None, "need_external": need_external},
    )

    if order.salesman_id:
        from app.models.user import User
        salesman_user = (await db.execute(
            select(User).where(User.employee_id == order.salesman_id)
        )).scalar_one_or_none()
        if salesman_user:
            await notify(
                db, recipient_id=salesman_user.id,
                title=f"政策已通过: {order.order_no}",
                content=f"订单 {order.order_no} 政策审批已通过，请扫码出库",
                entity_type="Order", entity_id=order.id,
            )
    return order


@router.post("/{order_id}/reject-policy-with-request", response_model=OrderResponse)
async def reject_policy_with_request(
    order_id: str,
    body: RejectPolicyBody,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """一次驳回：PolicyRequest.status=rejected + Order.status=policy_rejected。

    对应前端 PolicyApproval.tsx:93-111 rejectMutation 两步：
      1) PUT  /api/policies/requests/{id}                  (status: 'rejected')
      2) POST /api/orders/{order_id}/reject-policy          (rejection_reason)
    """
    from app.models.policy import PolicyRequest
    from app.models.base import PolicyRequestStatus

    require_role(user, "boss")

    # RLS + brand 白名单兜底，同 approve-policy-with-request
    order = (await db.execute(
        select(Order).where(Order.id == order_id)
    )).scalar_one_or_none()
    if order is None:
        raise HTTPException(404, "Order not found")
    roles = user.get("roles") or []
    if "admin" not in roles:
        brand_ids = user.get("brand_ids") or []
        if brand_ids and order.brand_id and order.brand_id not in brand_ids:
            raise HTTPException(404, "Order not found")
    if order.status not in (
        OrderStatus.POLICY_PENDING_INTERNAL,
        OrderStatus.POLICY_PENDING_EXTERNAL,
    ):
        raise HTTPException(400, f"Cannot reject: order is in '{order.status}'")

    pr = (await db.execute(
        select(PolicyRequest).where(
            PolicyRequest.order_id == order_id,
            PolicyRequest.status.in_([
                PolicyRequestStatus.PENDING_INTERNAL,
                PolicyRequestStatus.PENDING_EXTERNAL,
            ]),
        )
    )).scalar_one_or_none()

    if pr:
        pr.status = PolicyRequestStatus.REJECTED

    order.status = OrderStatus.REJECTED  # enum value = 'policy_rejected'
    order.rejection_reason = body.rejection_reason

    await db.flush()
    await log_audit(
        db, action="reject_policy_with_request", entity_type="Order",
        entity_id=order.id, user=user,
        changes={"rejection_reason": body.rejection_reason, "policy_request_id": pr.id if pr else None},
    )

    if order.salesman_id:
        from app.models.user import User
        salesman_user = (await db.execute(
            select(User).where(User.employee_id == order.salesman_id)
        )).scalar_one_or_none()
        if salesman_user:
            await notify(
                db, recipient_id=salesman_user.id,
                title=f"政策被驳回: {order.order_no}",
                content=f"订单 {order.order_no} 政策被驳回，原因: {body.rejection_reason}，请重新提交",
                entity_type="Order", entity_id=order.id,
            )
    return order


# ── Business: delivery & payment confirmation ──────────────────────


class DeliveryUploadBody(BaseModel):
    photo_urls: list[str]


class PaymentVoucherBody(BaseModel):
    voucher_urls: list[str]
    amount: Decimal  # 本次登记金额（必填）
    source_type: str | None = "customer"  # customer / employee_advance（业务员垫付补款）
    payment_method: str | None = None


@router.post("/{order_id}/upload-delivery", response_model=OrderResponse)
async def upload_delivery(
    order_id: str, body: DeliveryUploadBody, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """shipped → delivered: upload delivery photos and confirm delivery."""
    require_role(user, "boss", "salesman", "warehouse")
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    if order.status != OrderStatus.SHIPPED:
        raise HTTPException(400, f"订单状态为 '{order.status}'，只有已出库的订单才能确认送达")

    now = datetime.now(timezone.utc)
    order.delivery_photos = body.photo_urls
    order.status = OrderStatus.DELIVERED
    order.delivered_at = now

    await _ensure_order_receivable(db, order)

    await db.flush()
    await log_audit(db, action="upload_delivery", entity_type="Order", entity_id=order.id, user=user)
    await notify_roles(
        db, role_codes=["admin", "boss", "finance"],
        title=f"已送达: {order.order_no}",
        content=f"订单 {order.order_no} 已送达，请确认收款",
        entity_type="Order", entity_id=order.id,
    )
    return order


@router.post("/{order_id}/upload-payment-voucher", response_model=OrderResponse)
async def upload_payment_voucher(
    order_id: str, body: PaymentVoucherBody, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """业务员上传收款凭证 — 只建 pending Receipt，**不动账**。

    P2c 行为：
    - 新建 Receipt 状态为 'pending_confirmation'
    - 订单 payment_status 置为 PENDING_CONFIRMATION（有任一待审就是这个状态）
    - 不加账户余额、不写 fund_flow、不生成 commission、不刷 KPI
    - 这些副作用由财务在审批中心 "确认收款" 时才触发

    此前行为（凭证一上传就进账）的业务风险：任何业务员能伪造一条收款把公司账算多。
    现在必须经财务审核。
    """
    require_role(user, "boss", "finance", "salesman")
    from app.models.finance import Receipt
    from app.models.base import OrderPaymentMethod, PaymentStatus
    from app.models.product import Account

    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(400, f"订单状态为 '{order.status}'，只有已送达的订单才能上传收款凭证")
    if body.amount <= 0:
        raise HTTPException(400, "金额必须大于 0")

    # 凭证累加（历史 + 新增）
    existing_urls = order.payment_voucher_urls or []
    order.payment_voucher_urls = existing_urls + body.voucher_urls

    # account_id 暂不绑定 master 账户：业务员因 RLS 看不到 master，但此时
    # 本来也不该动账。财务在 confirm_payment 阶段才真正关联 master 并动账。
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    receipt = Receipt(
        id=str(uuid.uuid4()),
        receipt_no=f"RC-{now_str}-{uuid.uuid4().hex[:6]}",
        customer_id=order.customer_id,
        order_id=order.id,
        brand_id=order.brand_id,
        account_id=None,  # 审批通过时由 confirm_payment 填 master.id
        amount=body.amount,
        payment_method=body.payment_method or OrderPaymentMethod.BANK,
        receipt_date=datetime.now(timezone.utc).date(),
        source_type=body.source_type or "customer",
        status="pending_confirmation",
        notes=f"订单 {order.order_no} 收款（{body.source_type or 'customer'}）",
    )
    db.add(receipt)

    # 订单 payment_status 置为待审批（只要有任一 pending Receipt 就是这个状态）
    order.payment_status = PaymentStatus.PENDING_CONFIRMATION

    await db.flush()
    await log_audit(db, action="upload_payment_voucher", entity_type="Order", entity_id=order.id,
                    changes={"amount": float(body.amount), "source_type": body.source_type,
                             "receipt_id": receipt.id}, user=user)

    # 通知财务：有待审凭证
    await notify_roles(
        db, role_codes=["admin", "boss", "finance"],
        title=f"待审凭证：{order.order_no}",
        content=f"业务员上传了 ¥{body.amount} 的收款凭证，请在审批中心确认。",
        entity_type="Order", entity_id=order.id,
    )
    return order


@router.post("/{order_id}/confirm-payment", response_model=OrderResponse)
async def confirm_payment(
    order_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """财务/老板审批此订单所有 pending Receipt —— 动账 + 订单完成。

    按用户 D3 Q1=B 决策：一个订单的多条凭证一起审批（one-fails-all-fails）。
    本端点做三件事：
      1. 找该订单所有 status='pending_confirmation' 的 Receipt
      2. 对每条：加 master 现金池余额 + 写 fund_flow + 状态改 confirmed
      3. 重算订单 payment_status（按已确认总额）；若全款则 status=completed

    若订单没有 pending Receipt（历史订单走旧流程已入账），退回旧行为：仅 delivered→completed。
    """
    require_role(user, "boss", "finance")
    from app.models.finance import Receipt
    from app.models.base import PaymentStatus
    from app.api.routes.accounts import record_fund_flow
    from app.models.product import Account
    from app.services.receipt_service import (
        apply_per_receipt_effects,
        apply_post_confirmation_effects,
    )

    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(400, f"订单状态为 '{order.status}'，只有已送达的订单才能确认收款")

    pending_receipts = (await db.execute(
        select(Receipt).where(
            Receipt.order_id == order.id,
            Receipt.status == "pending_confirmation",
        ).order_by(Receipt.created_at)
    )).scalars().all()

    now = datetime.now(timezone.utc)
    emp_id = user.get("employee_id")
    prev_payment_status = order.payment_status

    if pending_receipts:
        master_cash = (await db.execute(
            select(Account).where(Account.level == 'master', Account.account_type == 'cash')
        )).scalar_one_or_none()
        if not master_cash:
            raise HTTPException(400, "未配置公司总资金池（master 现金账户）")

        # 批量确认：每条 Receipt 加账户 + 记流水 + 改 status + 分摊应收
        for r in pending_receipts:
            master_cash.balance += Decimal(str(r.amount))
            await record_fund_flow(
                db, account_id=master_cash.id, flow_type='credit', amount=r.amount,
                balance_after=master_cash.balance, related_type='receipt', related_id=r.id,
                notes=f"订单收款 {order.order_no}（审批确认）", created_by=emp_id,
                brand_id=order.brand_id,
            )
            # 补填 account_id：业务员上传时因 RLS 看不到 master，审批时填上
            if r.account_id is None:
                r.account_id = master_cash.id
            r.status = "confirmed"
            r.confirmed_at = now
            r.confirmed_by = emp_id
            # 应收账款分摊（每条 Receipt 单独跑一次）
            await apply_per_receipt_effects(db, r, order)

        await db.flush()

    # 重算 payment_status：按已 confirmed 的 Receipt 累计
    total_confirmed = (await db.execute(
        select(func.coalesce(func.sum(Receipt.amount), 0)).where(
            Receipt.order_id == order.id,
            Receipt.status == "confirmed",
        )
    )).scalar_one()
    target_amount = order.customer_paid_amount or order.total_amount

    if Decimal(str(total_confirmed)) >= target_amount:
        order.payment_status = PaymentStatus.FULLY_PAID
        order.status = OrderStatus.COMPLETED
        order.completed_at = now
    elif total_confirmed > 0:
        order.payment_status = PaymentStatus.PARTIALLY_PAID
    # total_confirmed == 0: 保持原状（兜底）

    await db.flush()

    # 订单层副作用一次性触发：Commission 生成 / KPI 刷新 / 里程碑通知
    # 传本次刚 confirm 的金额和，里程碑 prev_rate 用它算（否则 partial confirm 会推错档）
    newly_confirmed = sum((Decimal(str(r.amount)) for r in pending_receipts), Decimal("0"))
    await apply_post_confirmation_effects(
        db, order, user, prev_payment_status, newly_confirmed_amount=newly_confirmed,
    )

    await log_audit(
        db, action="confirm_payment", entity_type="Order", entity_id=order.id,
        changes={"confirmed_receipt_count": len(pending_receipts),
                 "confirmed_amount": float(sum(Decimal(str(r.amount)) for r in pending_receipts))},
        user=user,
    )

    if order.salesman_id and order.status == OrderStatus.COMPLETED:
        from app.models.user import User
        salesman_user = (await db.execute(
            select(User).where(User.employee_id == order.salesman_id)
        )).scalar_one_or_none()
        if salesman_user:
            await notify(
                db, recipient_id=salesman_user.id,
                title=f"收款已确认: {order.order_no}",
                content=f"订单 {order.order_no} 收款已确认，订单完成",
                entity_type="Order", entity_id=order.id,
            )
    return order


class RejectReceiptsBody(BaseModel):
    reason: str = ""


@router.post("/{order_id}/reject-payment-receipts", response_model=OrderResponse)
async def reject_payment_receipts(
    order_id: str, body: RejectReceiptsBody, user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    """财务拒绝此订单所有 pending Receipt（D3 Q1=B: 一起拒绝）。

    行为：
      - Receipt.status = 'rejected'，记原因
      - 订单 payment_status 回退：看还有没有已确认的 Receipt
      - 通知业务员

    不删除 Receipt（保留存根）。业务员可重新上传。
    """
    require_role(user, "boss", "finance")
    from app.models.finance import Receipt
    from app.models.base import PaymentStatus

    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")

    pending_receipts = (await db.execute(
        select(Receipt).where(
            Receipt.order_id == order.id,
            Receipt.status == "pending_confirmation",
        )
    )).scalars().all()

    if not pending_receipts:
        raise HTTPException(400, "此订单没有待审的凭证")

    now = datetime.now(timezone.utc)
    emp_id = user.get("employee_id")
    reason = body.reason or ""

    for r in pending_receipts:
        r.status = "rejected"
        r.confirmed_at = now  # 处理时间
        r.confirmed_by = emp_id
        r.rejected_reason = reason

    await db.flush()

    # 重算订单 payment_status：回退到"已 confirmed 的金额"对应状态
    total_confirmed = (await db.execute(
        select(func.coalesce(func.sum(Receipt.amount), 0)).where(
            Receipt.order_id == order.id,
            Receipt.status == "confirmed",
        )
    )).scalar_one()
    target_amount = order.customer_paid_amount or order.total_amount

    if Decimal(str(total_confirmed)) >= target_amount:
        order.payment_status = PaymentStatus.FULLY_PAID  # 不该发生但兜底
    elif total_confirmed > 0:
        order.payment_status = PaymentStatus.PARTIALLY_PAID
    else:
        order.payment_status = PaymentStatus.UNPAID

    await db.flush()
    await log_audit(
        db, action="reject_payment_receipts", entity_type="Order", entity_id=order.id,
        changes={"rejected_count": len(pending_receipts), "reason": reason}, user=user,
    )

    # 通知业务员
    if order.salesman_id:
        from app.models.user import User
        salesman_user = (await db.execute(
            select(User).where(User.employee_id == order.salesman_id)
        )).scalar_one_or_none()
        if salesman_user:
            await notify(
                db, recipient_id=salesman_user.id,
                title=f"凭证被拒：{order.order_no}",
                content=f"{len(pending_receipts)} 条待审凭证被拒绝。原因：{reason or '未说明'}。请重新上传。",
                entity_type="Order", entity_id=order.id,
            )
    return order


@router.post("/{order_id}/resubmit", response_model=OrderResponse)
async def resubmit_order(
    order_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """policy_rejected → pending: allow re-editing and resubmission."""
    require_role(user, "boss", "salesman", "sales_manager")
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    if order.status != OrderStatus.REJECTED:
        raise HTTPException(400, f"订单状态为 '{order.status}'，只有被驳回的订单才能重新提交")

    order.status = OrderStatus.PENDING
    order.rejection_reason = None
    await db.flush()
    await log_audit(db, action="resubmit_order", entity_type="Order", entity_id=order.id, user=user)
    return order


# ── Business: order profit (PRD §3.3.1) ─────────────────────────────


class ProfitItemDetail(BaseModel):
    product_id: str | None
    revenue: float
    cost: float
    gross_profit: float


class OrderProfitResponse(BaseModel):
    order_id: str
    total_revenue: float
    total_cost: float
    gross_profit: float
    policy_settlement_income: float
    penalty_deduction: float
    net_profit: float
    margin_pct: float
    items: list[ProfitItemDetail]


@router.get("/{order_id}/profit", response_model=OrderProfitResponse)
async def get_order_profit(order_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Compute-on-read order profit per PRD §3.3.1:
    profit = (revenue - cost) + policy_settlement_income - penalty_deduction
    """
    from app.models.policy import PolicyRequest, PolicyClaim, ClaimSettlementLink
    from app.models.inspection import InspectionCase

    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")

    items_detail: list[ProfitItemDetail] = []
    total_revenue = Decimal("0")
    total_cost = Decimal("0")

    for oi in order.items:
        revenue = Decimal(str(oi.unit_price)) * oi.quantity
        allocs = (
            await db.execute(
                select(StockOutAllocation).where(StockOutAllocation.order_item_id == oi.id)
            )
        ).scalars().all()

        cost = sum(
            (Decimal(str(a.allocated_cost_price)) * a.allocated_quantity for a in allocs),
            Decimal("0"),
        )
        if not allocs and oi.cost_price_snapshot:
            cost = Decimal(str(oi.cost_price_snapshot)) * oi.quantity

        total_revenue += revenue
        total_cost += cost
        items_detail.append(ProfitItemDetail(
            product_id=oi.product_id,
            revenue=float(revenue),
            cost=float(cost),
            gross_profit=float(revenue - cost),
        ))

    # Policy settlement income: sum of settled amounts from claims linked to this order
    policy_income = Decimal("0")
    policy_requests = (
        await db.execute(
            select(PolicyRequest).where(PolicyRequest.order_id == order_id)
        )
    ).scalars().all()
    for pr in policy_requests:
        claims = (
            await db.execute(
                select(PolicyClaim)
                .join(PolicyClaim.items)
                .where(PolicyClaim.items.any())
            )
        ).scalars().all()
        # Simpler: sum claim.settled_amount for claims linked via usage_records
        from app.models.policy import PolicyUsageRecord, PolicyClaimItem
        usage_ids = (
            await db.execute(
                select(PolicyUsageRecord.id).where(PolicyUsageRecord.policy_request_id == pr.id)
            )
        ).scalars().all()
        if usage_ids:
            claim_items = (
                await db.execute(
                    select(PolicyClaimItem).where(PolicyClaimItem.source_usage_record_id.in_(usage_ids))
                )
            ).scalars().all()
            policy_income += sum((Decimal(str(ci.approved_amount)) for ci in claim_items), Decimal("0"))

    # Penalty deduction: sum of penalty_amount from inspection cases linked to this order
    penalty = Decimal("0")
    cases = (
        await db.execute(
            select(InspectionCase).where(InspectionCase.original_order_id == order_id)
        )
    ).scalars().all()
    for c in cases:
        penalty += Decimal(str(c.penalty_amount))
        penalty += Decimal(str(c.rebate_deduction_amount))

    gross_profit = total_revenue - total_cost
    net_profit = gross_profit + policy_income - penalty
    margin_pct = float(net_profit / total_revenue * 100) if total_revenue > 0 else 0.0

    return OrderProfitResponse(
        order_id=order.id,
        total_revenue=float(total_revenue),
        total_cost=float(total_cost),
        gross_profit=float(gross_profit),
        policy_settlement_income=float(policy_income),
        penalty_deduction=float(penalty),
        net_profit=float(net_profit),
        margin_pct=round(margin_pct, 2),
        items=items_detail,
    )
