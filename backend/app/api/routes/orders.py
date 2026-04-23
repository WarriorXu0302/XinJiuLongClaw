"""
Order API routes — CRUD + policy flow + confirm-delivery + profit.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.permissions import apply_data_scope, require_role
from app.core.security import CurrentUser
from app.models.base import CustomerSettlementMode, OrderStatus
from app.models.customer import Customer, Receivable
from app.models.inventory import StockOutAllocation
from app.models.order import Order, OrderItem
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


@router.post("", response_model=OrderResponse, status_code=201)
async def create_order(body: OrderCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "salesman", "sales_manager")
    from app.models.product import Product
    from app.models.policy_template import PolicyTemplate

    # 必选政策模板，提供指导价（required_unit_price）和客户到手价（customer_unit_price）
    tmpl = await db.get(PolicyTemplate, body.policy_template_id)
    if not tmpl:
        raise HTTPException(400, "政策模板不存在")
    if not tmpl.is_active:
        raise HTTPException(400, "政策模板已停用")
    if tmpl.required_unit_price is None:
        raise HTTPException(400, "政策模板未配置指导价（required_unit_price）")

    # 商品必须属于模板同一品牌
    brand_id = tmpl.brand_id
    for it in body.items:
        product = await db.get(Product, it.product_id)
        if not product:
            raise HTTPException(400, f"商品 {it.product_id} 不存在")
        if brand_id and product.brand_id != brand_id:
            raise HTTPException(400, "商品品牌与政策模板不符")
        if brand_id is None:
            brand_id = product.brand_id

    guide_price = Decimal(str(tmpl.required_unit_price))
    customer_price = Decimal(str(tmpl.customer_unit_price or tmpl.required_unit_price))
    if body.deal_unit_price is not None:
        customer_price = Decimal(str(body.deal_unit_price))

    order = Order(
        id=str(uuid.uuid4()),
        order_no=_generate_order_no(),
        customer_id=body.customer_id,
        salesman_id=body.salesman_id,
        brand_id=brand_id,
        settlement_mode_snapshot=body.settlement_mode_snapshot,
        settlement_mode=body.settlement_mode,
        advance_payer_id=body.advance_payer_id,
        warehouse_id=body.warehouse_id,
        policy_template_id=tmpl.id,
        notes=body.notes,
    )

    total = Decimal("0")  # 按指导价的订单总额（公司应收）
    total_bottles = 0
    bpc_map: dict[str, int] = {}
    for it in body.items:
        if it.product_id and it.product_id not in bpc_map:
            prod = await db.get(Product, it.product_id)
            bpc_map[it.product_id] = prod.bottles_per_case if prod else 6
        bpc = bpc_map.get(it.product_id or '', 6)
        bottles = it.quantity * bpc if it.quantity_unit == '箱' else it.quantity

        # unit_price 强制使用政策模板指导价，忽略前端传入
        oi = OrderItem(
            id=str(uuid.uuid4()),
            order_id=order.id,
            product_id=it.product_id,
            quantity=it.quantity,
            quantity_unit=it.quantity_unit,
            unit_price=guide_price,
        )
        order.items.append(oi)
        total += guide_price * bottles
        total_bottles += bottles

    # 政策模板箱数校验：min_cases = 严格最低箱数（白酒政策按件匹配）
    total_cases = sum(
        it.quantity if it.quantity_unit == "箱" else 0
        for it in body.items
    )
    if tmpl.min_cases and total_cases < tmpl.min_cases:
        raise HTTPException(400, f"政策模板要求最低 {tmpl.min_cases} 箱，当前 {total_cases} 箱")
    if tmpl.max_cases and total_cases > tmpl.max_cases:
        raise HTTPException(400, f"政策模板最高 {tmpl.max_cases} 箱，当前 {total_cases} 箱")

    order.total_amount = total

    # 客户到手价与政策差
    order.deal_unit_price = customer_price
    order.deal_amount = customer_price * total_bottles
    order.policy_gap = total - order.deal_amount
    order.policy_value = tmpl.total_policy_value
    order.policy_surplus = (tmpl.total_policy_value or Decimal("0")) - order.policy_gap

    # 结算模式：统一 customer_paid_amount 语义 = "公司对该订单期望收到的钱"
    # customer_pay   客户按指导价全额付 → 公司应收 total（26,550）
    # employee_pay   业务员垫差额 → 公司应收 total（客户 19,500 + 业务员 7,050 两笔凭证凑齐）
    # company_pay    公司垫差额 → 公司应收 deal_amount（19,500，公司不向自己要钱）
    if body.settlement_mode == "customer_pay":
        order.customer_paid_amount = total
        order.policy_receivable = Decimal("0")
    elif body.settlement_mode == "employee_pay":
        order.customer_paid_amount = total  # 公司按指导价应收；业务员要补足政策差
        order.policy_receivable = order.policy_gap  # 等厂家兑付后返业务员
    elif body.settlement_mode == "company_pay":
        order.customer_paid_amount = order.deal_amount  # 公司让利，只收客户那部分
        order.policy_receivable = order.policy_gap  # 等厂家兑付后留公司 F 类
    else:
        raise HTTPException(400, "settlement_mode 必须为 customer_pay/employee_pay/company_pay")

    db.add(order)
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
    """Upload payment voucher + register a Receipt (累加式；自动更新 payment_status)。"""
    require_role(user, "boss", "finance", "salesman")
    from app.models.finance import Receipt
    from app.models.base import OrderPaymentMethod, PaymentStatus
    from app.api.routes.accounts import record_fund_flow
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

    # 建 Receipt —— 自动进 master 现金池（收款统一入口）
    master_cash = (await db.execute(
        select(Account).where(Account.level == 'master', Account.account_type == 'cash')
    )).scalar_one_or_none()
    if not master_cash:
        raise HTTPException(400, "未配置公司总资金池（master 现金账户），请先到账户管理创建")

    now_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    receipt = Receipt(
        id=str(uuid.uuid4()),
        receipt_no=f"RC-{now_str}-{uuid.uuid4().hex[:6]}",
        customer_id=order.customer_id,
        order_id=order.id,
        brand_id=order.brand_id,
        account_id=master_cash.id,
        amount=body.amount,
        payment_method=body.payment_method or OrderPaymentMethod.BANK,
        receipt_date=datetime.now(timezone.utc).date(),
        source_type=body.source_type or "customer",
        notes=f"订单 {order.order_no} 收款（{body.source_type or 'customer'}）",
    )
    db.add(receipt)
    master_cash.balance += body.amount
    await record_fund_flow(
        db, account_id=master_cash.id, flow_type='credit', amount=body.amount,
        balance_after=master_cash.balance, related_type='receipt', related_id=receipt.id,
        notes=f"订单收款 {order.order_no}", created_by=user.get('employee_id'),
        brand_id=order.brand_id,
    )
    # 先 flush 让新 Receipt 落库，下面的 SUM 才能查到
    await db.flush()

    # 更新 payment_status
    total_received = (await db.execute(
        select(func.coalesce(func.sum(Receipt.amount), 0)).where(Receipt.order_id == order.id)
    )).scalar_one()
    target_amount = order.customer_paid_amount or order.total_amount
    prev_status = order.payment_status
    if Decimal(str(total_received)) >= target_amount:
        order.payment_status = PaymentStatus.FULLY_PAID
    elif total_received > 0:
        order.payment_status = PaymentStatus.PARTIALLY_PAID

    await db.flush()
    await log_audit(db, action="upload_payment_voucher", entity_type="Order", entity_id=order.id,
                    changes={"amount": float(body.amount), "source_type": body.source_type}, user=user)

    # 只在全款跃升时才通知财务；部分付款不打扰
    if prev_status != PaymentStatus.FULLY_PAID and order.payment_status == PaymentStatus.FULLY_PAID:
        await notify_roles(
            db, role_codes=["admin", "boss", "finance"],
            title=f"订单已全款：{order.order_no}",
            content=f"订单 {order.order_no} 已收齐 ¥{target_amount}，请在审批中心确认收款。",
            entity_type="Order", entity_id=order.id,
        )
    return order


@router.post("/{order_id}/confirm-payment", response_model=OrderResponse)
async def confirm_payment(
    order_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """delivered → completed: boss/finance confirms payment received."""
    require_role(user, "boss", "finance")
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(400, f"订单状态为 '{order.status}'，只有已送达的订单才能确认收款")

    order.status = OrderStatus.COMPLETED
    order.completed_at = datetime.now(timezone.utc)
    await db.flush()
    await log_audit(db, action="confirm_payment", entity_type="Order", entity_id=order.id, user=user)
    if order.salesman_id:
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
