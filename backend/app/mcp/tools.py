"""
MCP Tools — functions exposed to openclaw (AI Gateway) via FastAPI.

These tools are called by the AI agent in Feishu group chats.
All requests must carry an authenticated token in headers.
"""
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.mcp.auth import require_mcp_role
from app.mcp.deps import get_mcp_db
from app.models.base import (
    ClaimStatusEnum,
    ExecutionStatus,
    ManufacturerExternalStatus,
    PolicyRequestStatus,
)
from app.models.external import ManufacturerExternalIdentity
from app.models.finance import ManufacturerSettlement
from app.models.inventory import InventoryBarcode, StockFlow
from app.models.notification_log import NotificationLog
from app.models.order import Order, OrderItem
from app.models.policy import PolicyClaim, PolicyRequest, PolicyUsageRecord
from app.services.audit_service import log_audit

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════
# Tool 1: allocate_settlement_to_claims  (preview only — no writes)
# ═══════════════════════════════════════════════════════════════════════


class AllocationSuggestionItem(BaseModel):
    claim_id: str
    claim_no: str
    claim_batch_period: str
    claim_amount: float
    unsettled_amount: float
    suggested_amount: float


class AllocationPreviewResponse(BaseModel):
    settlement_id: str
    settlement_no: str
    total_available: float
    suggestions: list[AllocationSuggestionItem]


class AllocationPreviewRequest(BaseModel):
    settlement_id: str


@router.post(
    "/allocate-settlement-to-claims",
    response_model=AllocationPreviewResponse,
)
async def allocate_settlement_to_claims(
    body: AllocationPreviewRequest,
    db: AsyncSession = Depends(get_mcp_db),
):
    """AI generates settlement-to-claims allocation suggestions.

    Returns a preview JSON array. Does NOT write to claim_settlement_links.
    Finance must confirm via /allocation-confirm to persist.
    """
    require_mcp_role(db.info.get("mcp_user", {}), "boss", "finance")
    settlement_id = body.settlement_id

    # Load settlement
    settlement = await db.get(ManufacturerSettlement, settlement_id)
    if settlement is None:
        raise HTTPException(404, "Settlement not found")
    if settlement.unsettled_amount <= 0:
        raise HTTPException(400, "Settlement has no unsettled balance")

    # Find matching pending claims
    stmt = (
        select(PolicyClaim)
        .where(PolicyClaim.unsettled_amount > 0)
    )
    # Scope to same manufacturer / brand if set on the settlement
    if settlement.manufacturer_id:
        stmt = stmt.where(PolicyClaim.manufacturer_id == settlement.manufacturer_id)
    if settlement.brand_id:
        stmt = stmt.where(PolicyClaim.brand_id == settlement.brand_id)

    stmt = stmt.order_by(PolicyClaim.created_at.asc())
    claims: list[PolicyClaim] = list((await db.execute(stmt)).scalars().all())

    if not claims:
        raise HTTPException(404, "No pending claims found for this settlement")

    # ── Proportional allocation by unsettled_amount ──────────────────
    available = Decimal(str(settlement.unsettled_amount))
    total_unsettled = sum(Decimal(str(c.unsettled_amount)) for c in claims)

    suggestions: list[AllocationSuggestionItem] = []
    distributed = Decimal("0.00")

    for idx, claim in enumerate(claims):
        claim_unsettled = Decimal(str(claim.unsettled_amount))

        if available >= total_unsettled:
            # Enough to cover everything — allocate each claim's full unsettled
            share = claim_unsettled
        elif idx == len(claims) - 1:
            # Last item gets remainder
            share = min(available - distributed, claim_unsettled)
        else:
            share = (available * claim_unsettled / total_unsettled).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            share = min(share, claim_unsettled)

        distributed += share

        suggestions.append(
            AllocationSuggestionItem(
                claim_id=claim.id,
                claim_no=claim.claim_no,
                claim_batch_period=claim.claim_batch_period,
                claim_amount=float(claim.claim_amount),
                unsettled_amount=float(claim.unsettled_amount),
                suggested_amount=float(share),
            )
        )

    return AllocationPreviewResponse(
        settlement_id=settlement.id,
        settlement_no=settlement.settlement_no,
        total_available=float(settlement.unsettled_amount),
        suggestions=suggestions,
    )


# ═══════════════════════════════════════════════════════════════════════
# Tool 2: external_approve_and_fill_scheme
# ═══════════════════════════════════════════════════════════════════════


class ExternalApproveRequest(BaseModel):
    policy_request_id: str
    scheme_no: str


class ExternalApproveResponse(BaseModel):
    policy_request_id: str
    scheme_no: str
    status: str
    message: str


@router.post(
    "/external-approve-and-fill-scheme",
    response_model=ExternalApproveResponse,
)
async def external_approve_and_fill_scheme(
    body: ExternalApproveRequest,
    db: AsyncSession = Depends(get_db),
    x_external_open_id: str = Header(..., alias="X-External-Open-Id"),
):
    """External manufacturer staff approves a policy and fills in scheme_no.

    Auth: the caller's Feishu open_id must be present in
    manufacturer_external_identities with status=active.
    Brand scope is enforced via the identity's brand_scope JSONB field.
    """

    # ── 1. Authenticate external identity ────────────────────────────
    identity = (
        await db.execute(
            select(ManufacturerExternalIdentity).where(
                ManufacturerExternalIdentity.open_id == x_external_open_id,
                ManufacturerExternalIdentity.status
                == ManufacturerExternalStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()

    if identity is None:
        raise HTTPException(
            403, "External identity not found or disabled"
        )

    # Update last seen
    identity.last_seen_at = datetime.now(timezone.utc)

    # ── 2. Load & validate the policy request ────────────────────────
    pr = (
        await db.execute(
            select(PolicyRequest)
            .where(PolicyRequest.id == body.policy_request_id)
            .options(selectinload(PolicyRequest.order))
            .with_for_update()
        )
    ).scalar_one_or_none()

    if pr is None:
        raise HTTPException(404, "PolicyRequest not found")

    if pr.status != PolicyRequestStatus.PENDING_EXTERNAL:
        raise HTTPException(
            400,
            f"PolicyRequest is in status '{pr.status}', "
            f"expected '{PolicyRequestStatus.PENDING_EXTERNAL}'",
        )

    # ── 3. Brand scope authorization ─────────────────────────────────
    #   Determine which brand this policy request relates to, then check
    #   it falls within the identity's brand_scope.
    request_brand_id = _extract_brand_id(pr)
    brand_scope: list[str] | None = identity.brand_scope  # type: ignore[assignment]

    if request_brand_id and brand_scope:
        if request_brand_id not in brand_scope:
            raise HTTPException(
                403,
                f"Brand {request_brand_id} is outside your authorized scope",
            )

    # ── 4. Apply approval ────────────────────────────────────────────
    pr.scheme_no = body.scheme_no
    pr.status = PolicyRequestStatus.APPROVED
    pr.manufacturer_approved_by = x_external_open_id

    await db.flush()
    await log_audit(
        db,
        action="external_approve",
        entity_type="PolicyRequest",
        entity_id=pr.id,
        actor_type="external",
        changes={"scheme_no": body.scheme_no, "open_id": x_external_open_id},
    )

    return ExternalApproveResponse(
        policy_request_id=pr.id,
        scheme_no=pr.scheme_no,
        status=pr.status,
        message="Policy approved and scheme_no filled successfully",
    )


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _extract_brand_id(pr: PolicyRequest) -> str | None:
    """Best-effort extraction of brand_id from a PolicyRequest.

    Priority:
      1. pr.brand_id  (direct field)
      2. policy_snapshot.brand_id  (explicit in snapshot JSONB)
      3. First order item's product.brand_id  (via relationship)
    """
    # 0. Direct field
    if pr.brand_id:
        return pr.brand_id

    # 1. Snapshot
    if pr.policy_snapshot and isinstance(pr.policy_snapshot, dict):
        bid = pr.policy_snapshot.get("brand_id")
        if bid:
            return str(bid)

    # 2. Order → items → product → brand
    if pr.order and pr.order.items:
        for item in pr.order.items:
            if item.product and item.product.brand_id:
                return item.product.brand_id

    return None


# ═══════════════════════════════════════════════════════════════════════
# Tool 3: query_barcode_tracing
# ═══════════════════════════════════════════════════════════════════════


class BarcodeTracingRequest(BaseModel):
    barcode: str


class BarcodeTracingResponse(BaseModel):
    barcode: str
    barcode_type: Optional[str] = None
    product_name: Optional[str] = None
    batch_no: Optional[str] = None
    warehouse_name: Optional[str] = None
    status: Optional[str] = None
    stock_in_flow_no: Optional[str] = None
    stock_out_flow_no: Optional[str] = None
    source_order_no: Optional[str] = None
    customer_name: Optional[str] = None
    salesman_name: Optional[str] = None
    message: str = ""


@router.post(
    "/query-barcode-tracing",
    response_model=BarcodeTracingResponse,
)
async def query_barcode_tracing(
    body: BarcodeTracingRequest,
    db: AsyncSession = Depends(get_mcp_db),
):
    """Trace a barcode through the full supply chain:
    barcode → batch → stock_flow → order → customer → salesman.
    """
    require_mcp_role(db.info.get("mcp_user", {}), "boss", "warehouse", "salesman", "sales_manager", "finance")
    bc = (
        await db.execute(
            select(InventoryBarcode).where(InventoryBarcode.barcode == body.barcode)
        )
    ).scalar_one_or_none()

    if bc is None:
        return BarcodeTracingResponse(barcode=body.barcode, message="条码未找到")

    result = BarcodeTracingResponse(
        barcode=bc.barcode,
        barcode_type=bc.barcode_type,
        product_name=bc.product.name if bc.product else None,
        batch_no=bc.batch_no,
        warehouse_name=bc.warehouse.name if bc.warehouse else None,
        status=bc.status,
    )

    # Stock-in flow
    if bc.stock_in_id:
        in_flow = await db.get(StockFlow, bc.stock_in_id)
        if in_flow:
            result.stock_in_flow_no = in_flow.flow_no

    # Stock-out flow → order → customer → salesman
    if bc.outbound_stock_flow_id:
        out_flow = await db.get(StockFlow, bc.outbound_stock_flow_id)
        if out_flow:
            result.stock_out_flow_no = out_flow.flow_no
            if out_flow.source_order_id:
                order = await db.get(Order, out_flow.source_order_id)
                if order:
                    result.source_order_no = order.order_no
                    if order.customer:
                        result.customer_name = order.customer.name
                    if order.salesman:
                        result.salesman_name = order.salesman.name

    result.message = "追溯完成"
    return result


# ═══════════════════════════════════════════════════════════════════════
# Tool 4: submit_policy_approval
# ═══════════════════════════════════════════════════════════════════════


class SubmitPolicyApprovalRequest(BaseModel):
    policy_request_id: str
    approval_target: str = "internal"  # "internal" or "external"


class SubmitPolicyApprovalResponse(BaseModel):
    policy_request_id: str
    new_status: str
    message: str


@router.post(
    "/submit-policy-approval",
    response_model=SubmitPolicyApprovalResponse,
)
async def submit_policy_approval(
    body: SubmitPolicyApprovalRequest,
    db: AsyncSession = Depends(get_mcp_db),
):
    """Submit a policy request for approval — moves status to pending_internal
    or pending_external depending on approval_target.
    """
    require_mcp_role(db.info.get("mcp_user", {}), "boss", "finance", "sales_manager", "salesman")
    pr = await db.get(PolicyRequest, body.policy_request_id)
    if pr is None:
        raise HTTPException(404, "PolicyRequest not found")

    if body.approval_target == "external":
        if pr.status != PolicyRequestStatus.APPROVED:
            raise HTTPException(
                400,
                f"Cannot submit to external: current status is '{pr.status}', "
                f"expected '{PolicyRequestStatus.APPROVED}'",
            )
        pr.status = PolicyRequestStatus.PENDING_EXTERNAL
    else:
        if pr.status != PolicyRequestStatus.PENDING_INTERNAL:
            raise HTTPException(
                400,
                f"Cannot submit to internal: current status is '{pr.status}', "
                f"expected '{PolicyRequestStatus.PENDING_INTERNAL}'",
            )
        pr.status = PolicyRequestStatus.APPROVED

    await db.flush()
    await log_audit(
        db,
        action="submit_policy_approval",
        entity_type="PolicyRequest",
        entity_id=pr.id,
        changes={"approval_target": body.approval_target, "new_status": pr.status},
    )

    return SubmitPolicyApprovalResponse(
        policy_request_id=pr.id,
        new_status=pr.status,
        message=f"已提交{'厂家' if body.approval_target == 'external' else '内部'}审批",
    )


# ═══════════════════════════════════════════════════════════════════════
# Tool 5: create_policy_usage_record
# ═══════════════════════════════════════════════════════════════════════


class CreateUsageRecordRequest(BaseModel):
    policy_request_id: str
    benefit_item_type: str
    usage_scene: Optional[str] = None
    usage_applicant_id: Optional[str] = None
    planned_amount: float = 0.0
    actual_amount: float = 0.0
    advance_payer_type: Optional[str] = None
    advance_employee_id: Optional[str] = None
    advance_customer_id: Optional[str] = None
    advance_company_account_id: Optional[str] = None


class CreateUsageRecordResponse(BaseModel):
    id: str
    policy_request_id: str
    benefit_item_type: str
    execution_status: str
    message: str


@router.post(
    "/create-policy-usage-record",
    response_model=CreateUsageRecordResponse,
    status_code=201,
)
async def create_policy_usage_record(
    body: CreateUsageRecordRequest,
    db: AsyncSession = Depends(get_mcp_db),
):
    """Create a policy usage record manually — for non-shipment scenarios
    where consumption is recorded by hand (e.g., tasting events).
    """
    require_mcp_role(db.info.get("mcp_user", {}), "boss", "finance", "salesman")
    pr = await db.get(PolicyRequest, body.policy_request_id)
    if pr is None:
        raise HTTPException(404, "PolicyRequest not found")
    if pr.status not in (
        PolicyRequestStatus.APPROVED,
    ):
        raise HTTPException(
            400,
            f"PolicyRequest status is '{pr.status}', must be approved first",
        )

    record = PolicyUsageRecord(
        id=str(uuid.uuid4()),
        policy_request_id=body.policy_request_id,
        benefit_item_type=body.benefit_item_type,
        usage_scene=body.usage_scene,
        usage_applicant_id=body.usage_applicant_id,
        planned_amount=Decimal(str(body.planned_amount)),
        actual_amount=Decimal(str(body.actual_amount)),
        advance_payer_type=body.advance_payer_type,
        advance_employee_id=body.advance_employee_id,
        advance_customer_id=body.advance_customer_id,
        advance_company_account_id=body.advance_company_account_id,
        execution_status=ExecutionStatus.PENDING,
        claim_status=ClaimStatusEnum.UNCLAIMED,
    )
    db.add(record)
    await db.flush()

    await log_audit(
        db,
        action="create_policy_usage_record",
        entity_type="PolicyUsageRecord",
        entity_id=record.id,
    )

    return CreateUsageRecordResponse(
        id=record.id,
        policy_request_id=record.policy_request_id,
        benefit_item_type=record.benefit_item_type,
        execution_status=record.execution_status,
        message="执行记录已创建",
    )


# ═══════════════════════════════════════════════════════════════════════
# Tool 6: push_manufacturer_update
# ═══════════════════════════════════════════════════════════════════════


class PushManufacturerUpdateRequest(BaseModel):
    channel: str = "feishu"
    recipient: str
    title: Optional[str] = None
    content: str
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[str] = None


class PushManufacturerUpdateResponse(BaseModel):
    notification_id: str
    status: str
    message: str


@router.post(
    "/push-manufacturer-update",
    response_model=PushManufacturerUpdateResponse,
    status_code=201,
)
async def push_manufacturer_update(
    body: PushManufacturerUpdateRequest,
    db: AsyncSession = Depends(get_mcp_db),
):
    """Record and push a manufacturer update notification.
    Creates a NotificationLog entry and returns structured card data.
    """
    require_mcp_role(db.info.get("mcp_user", {}), "boss", "finance", "sales_manager")
    log = NotificationLog(
        id=str(uuid.uuid4()),
        channel=body.channel,
        recipient=body.recipient,
        title=body.title,
        content=body.content,
        related_entity_type=body.related_entity_type,
        related_entity_id=body.related_entity_id,
        status="sent",
    )
    db.add(log)
    await db.flush()

    return PushManufacturerUpdateResponse(
        notification_id=log.id,
        status="sent",
        message="厂家动态已推送",
    )


# ═══════════════════════════════════════════════════════════════════════
# Tool 7: create_order_from_text
# ═══════════════════════════════════════════════════════════════════════


class CreateOrderFromTextRequest(BaseModel):
    text: str
    salesman_id: Optional[str] = None


class ParsedOrderItem(BaseModel):
    product_name: str
    quantity: int
    unit_price: float


class CreateOrderFromTextResponse(BaseModel):
    order_id: Optional[str] = None
    order_no: Optional[str] = None
    parsed_items: list[ParsedOrderItem]
    total_amount: float
    message: str


@router.post(
    "/create-order-from-text",
    response_model=CreateOrderFromTextResponse,
    status_code=201,
)
async def create_order_from_text(
    body: CreateOrderFromTextRequest,
    db: AsyncSession = Depends(get_mcp_db),
):
    """Parse natural language order text and create a structured order.

    Example input: "张三 青花郎 10箱 885"
    The AI agent pre-parses the text before calling this endpoint.
    This tool creates the order from the structured data extracted upstream.

    Note: In production, the AI agent in Feishu would parse the text first,
    then call this endpoint with structured data. For now, this tool
    demonstrates the flow by accepting raw text and performing basic parsing.
    """
    import re

    from app.models.product import Product
    from app.models.customer import Customer

    user = db.info.get("mcp_user", {})
    require_mcp_role(user, "boss", "salesman", "sales_manager")
    # salesman 身份硬绑定
    roles = user.get("roles") or []
    if "admin" not in roles and "boss" not in roles and "sales_manager" not in roles:
        emp_id = user.get("employee_id")
        if not emp_id:
            raise HTTPException(400, "当前用户未绑定员工档案")
        body.salesman_id = emp_id

    lines = body.text.strip().split("\n")
    if not lines:
        raise HTTPException(400, "Empty order text")

    # Simple pattern: customer_name product_name quantity unit_price
    parsed_items: list[ParsedOrderItem] = []
    customer_name: str | None = None
    total = Decimal("0.00")

    # 先尝试从文本中提取客户名、商品、数量
    # 支持多种自然语言格式：
    #   "张三 青花郎 10箱 885"（严格格式）
    #   "王永 买 5箱 青花郎"
    #   "青花郎 5箱"
    #   "给张三下单 青花郎53度500ml 10箱"
    full_text = " ".join(lines)

    # 提取数量（数字+箱/瓶/件）
    qty_match = re.search(r"(\d+)\s*[箱瓶件]", full_text)
    qty = int(qty_match.group(1)) if qty_match else 1

    # 提取商品名（匹配数据库中的产品）
    all_products = (await db.execute(select(Product))).scalars().all()
    matched_product = None
    for p in all_products:
        if p.name and p.name in full_text:
            matched_product = p
            break
        if p.code and p.code in full_text:
            matched_product = p
            break
    # 模糊匹配：品牌名
    if not matched_product:
        for p in all_products:
            brand_keywords = ['青花郎', '五粮液', '汾酒', '珍十五']
            for kw in brand_keywords:
                if kw in full_text and p.name and kw in p.name:
                    matched_product = p
                    break
            if matched_product:
                break

    if matched_product:
        price = float(matched_product.sale_price or 0)
        parsed_items.append(
            ParsedOrderItem(product_name=matched_product.name, quantity=qty, unit_price=price)
        )
        total += Decimal(str(price)) * qty

    # 提取客户名（排除商品名和数量后的中文词）
    all_customers = (await db.execute(select(Customer).limit(100))).scalars().all()
    for c in all_customers:
        if c.name and c.name in full_text:
            customer_name = c.name
            break

    if not parsed_items:
        return CreateOrderFromTextResponse(
            parsed_items=[],
            total_amount=0.0,
            message="无法解析订单文本，请检查格式",
        )

    # Look up customer
    customer_id = None
    if customer_name:
        cust = (
            await db.execute(
                select(Customer).where(Customer.name.ilike(f"%{customer_name}%")).limit(1)
            )
        ).scalar_one_or_none()
        if cust:
            customer_id = cust.id

    # Create order
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6]
    order_no = f"OD-{ts}-{short}"

    order = Order(
        id=str(uuid.uuid4()),
        order_no=order_no,
        customer_id=customer_id,
        salesman_id=body.salesman_id,
        total_amount=total,
    )
    db.add(order)
    await db.flush()

    # Create order items — try to match products by name
    for item in parsed_items:
        product = (
            await db.execute(
                select(Product)
                .where(Product.name.ilike(f"%{item.product_name}%"))
                .limit(1)
            )
        ).scalar_one_or_none()

        oi = OrderItem(
            id=str(uuid.uuid4()),
            order_id=order.id,
            product_id=product.id if product else None,
            quantity=item.quantity,
            unit_price=Decimal(str(item.unit_price)),
        )
        db.add(oi)

    await db.flush()
    await log_audit(
        db,
        action="create_order_from_text",
        entity_type="Order",
        entity_id=order.id,
        changes={"source_text": body.text},
    )

    return CreateOrderFromTextResponse(
        order_id=order.id,
        order_no=order.order_no,
        parsed_items=parsed_items,
        total_amount=float(total),
        message=f"订单已创建: {order_no}",
    )
