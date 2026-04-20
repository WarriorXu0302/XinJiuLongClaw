"""
Policy API routes — CRUD for policy requests and claims.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models.base import ClaimStatusEnum
from app.models.policy import (
    ClaimSettlementLink,
    PolicyClaim,
    PolicyClaimItem,
    PolicyRequest,
    PolicyUsageRecord,
)
from app.schemas.policy import (
    PolicyClaimCreate,
    PolicyClaimResponse,
    PolicyClaimUpdate,
    PolicyRequestCreate,
    PolicyRequestResponse,
    PolicyRequestUpdate,
    PolicyUsageRecordCreate,
    PolicyUsageRecordResponse,
    PolicyUsageRecordUpdate,
)
from app.services.audit_service import log_audit

router = APIRouter()


async def _trigger_advance_refund_if_fulfilled(db: AsyncSession, ri) -> None:
    """PolicyRequestItem 进入 fulfilled → 若 advance_payer 是员工/客户，自动生成 pending
    FinancePaymentRequest（垫付返还申请）。等老板在审批中心确认付款。
    金额 = settled_amount（到账+实物的实际结算值）。幂等：已有同 source 的请求不重建。
    """
    from app.models.finance import FinancePaymentRequest
    from app.models.base import PayeeType, PaymentRequestStatus
    from app.services.notification_service import notify_roles

    if ri.fulfill_status != "fulfilled":
        return
    if not ri.advance_payer_type or ri.advance_payer_type == "company":
        return  # 公司垫付不需要返还
    amount = Decimal(str(ri.settled_amount or 0))
    if amount <= 0:
        # settled_amount 未计算时兜底用 standard_total - actual_cost
        amount = Decimal(str(ri.standard_total or 0)) - Decimal(str(ri.actual_cost or 0))
    if amount <= 0:
        return

    # 幂等
    existing = (await db.execute(
        select(FinancePaymentRequest).where(
            FinancePaymentRequest.source_usage_record_id == None,
            FinancePaymentRequest.payee_type == ri.advance_payer_type,
            FinancePaymentRequest.payee_employee_id == (ri.advance_payer_id if ri.advance_payer_type == "employee" else None),
            FinancePaymentRequest.payee_customer_id == (ri.advance_payer_id if ri.advance_payer_type == "customer" else None),
            FinancePaymentRequest.amount == amount,
            FinancePaymentRequest.status != PaymentRequestStatus.CANCELLED,
        )
    )).scalar_one_or_none()
    if existing:
        return

    pr = await db.get(PolicyRequest, ri.policy_request_id)
    brand_id = pr.brand_id if pr else None

    # 默认付款账户 = 该品牌现金账户
    default_account_id = None
    if brand_id:
        from app.models.product import Account as _Acct
        acct = (await db.execute(
            select(_Acct).where(
                _Acct.brand_id == brand_id,
                _Acct.account_type == "cash",
                _Acct.level == "project",
            )
        )).scalar_one_or_none()
        if acct:
            default_account_id = acct.id

    now = datetime.now(timezone.utc)
    req = FinancePaymentRequest(
        id=str(uuid.uuid4()),
        request_no=f"AR-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}",
        brand_id=brand_id,
        payee_type=ri.advance_payer_type,
        payee_employee_id=ri.advance_payer_id if ri.advance_payer_type == "employee" else None,
        payee_customer_id=ri.advance_payer_id if ri.advance_payer_type == "customer" else None,
        amount=amount,
        status=PaymentRequestStatus.PENDING,
        payable_account_type="cash",
        payable_account_id=default_account_id,
    )
    db.add(req)
    await db.flush()

    await notify_roles(
        db, role_codes=["boss", "admin", "finance"],
        title=f"政策垫付已到账，{ri.advance_payer_type} 待返还 ¥{amount}",
        content=f"政策项 {ri.name}（方案 {ri.scheme_no or '-'}）已 fulfilled，请审批付款给垫付人。",
        entity_type="FinancePaymentRequest", entity_id=req.id,
    )


def _generate_claim_no() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"CL-{ts}-{short}"


# ═══════════════════════════════════════════════════════════════════
# PolicyRequest CRUD
# ═══════════════════════════════════════════════════════════════════


@router.post("/requests", status_code=201)
async def create_policy_request(
    body: PolicyRequestCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    from app.models.policy_request_item import PolicyRequestItem

    data = body.model_dump(exclude={"request_items"})
    pr = PolicyRequest(id=str(uuid.uuid4()), **data)
    db.add(pr)

    # Create structured request items from template benefits
    if body.request_items:
        for i, item in enumerate(body.request_items):
            suv = Decimal(str(item.standard_unit_value))
            st = suv * item.quantity
            uv = Decimal(str(item.unit_value))
            tv = uv * item.quantity
            ri = PolicyRequestItem(
                id=str(uuid.uuid4()),
                policy_request_id=pr.id,
                benefit_type=item.benefit_type,
                name=item.name,
                quantity=item.quantity,
                quantity_unit=item.quantity_unit,
                standard_unit_value=suv,
                standard_total=st,
                unit_value=uv,
                total_value=tv,
                product_id=item.product_id,
                is_material=item.is_material,
                fulfill_mode=item.fulfill_mode,
                advance_payer_type=item.advance_payer_type,
                advance_payer_id=item.advance_payer_id,
                sort_order=item.sort_order or i,
            )
            pr.request_items.append(ri)

    await db.flush()
    return _pr_to_response(pr)


def _pr_to_response(pr: PolicyRequest) -> dict:
    # Build nested order object for frontend
    order_dict = None
    if pr.order_id:
        try:
            o = pr.order
            if o:
                order_items = []
                try:
                    for oi in o.items:
                        order_items.append({
                            "product_name": oi.product.name if oi.product else None,
                            "quantity": oi.quantity,
                            "unit_price": str(oi.unit_price) if oi.unit_price else "0",
                        })
                except Exception:
                    pass
                order_dict = {
                    "order_no": o.order_no,
                    "total_amount": str(o.total_amount) if o.total_amount else "0",
                    "deal_unit_price": str(o.deal_unit_price) if o.deal_unit_price else None,
                    "deal_amount": str(o.deal_amount) if o.deal_amount else None,
                    "policy_gap": str(o.policy_gap) if o.policy_gap else None,
                    "policy_value": str(o.policy_value) if o.policy_value else None,
                    "policy_surplus": str(o.policy_surplus) if o.policy_surplus else None,
                    "settlement_mode": o.settlement_mode,
                    "customer": {"name": o.customer.name} if o.customer else None,
                    "salesman": {"name": o.salesman.name} if o.salesman else None,
                    "items": order_items,
                }
        except Exception:
            pass

    # Build nested customer object for frontend
    customer_dict = None
    if pr.customer_id:
        try:
            c = pr.customer
            if c:
                customer_dict = {"name": c.name}
        except Exception:
            pass

    d = {
        "id": pr.id, "request_source": pr.request_source, "approval_mode": pr.approval_mode,
        "order_id": pr.order_id, "customer_id": pr.customer_id, "target_name": pr.target_name,
        "usage_purpose": pr.usage_purpose, "brand_id": pr.brand_id,
        "order": order_dict,
        "customer": customer_dict,
        "policy_id": pr.policy_id, "scheme_no": pr.scheme_no,
        "policy_version_id": pr.policy_version_id,
        "policy_snapshot": pr.policy_snapshot, "material_items": pr.material_items,
        "policy_template_id": pr.policy_template_id,
        "total_policy_value": float(pr.total_policy_value) if pr.total_policy_value else None,
        "total_gap": float(pr.total_gap) if pr.total_gap else None,
        "settlement_mode": pr.settlement_mode,
        "internal_approved_by": pr.internal_approved_by,
        "manufacturer_approved_by": pr.manufacturer_approved_by,
        "status": pr.status,
        "created_at": str(pr.created_at) if pr.created_at else None,
        "updated_at": str(pr.updated_at) if pr.updated_at else None,
    }
    d["request_items"] = []
    for ri in pr.request_items:
        rid = {
            "id": ri.id, "benefit_type": ri.benefit_type, "name": ri.name,
            "quantity": ri.quantity,
            "quantity_unit": ri.quantity_unit if hasattr(ri, 'quantity_unit') else "次",
            "standard_unit_value": float(ri.standard_unit_value) if ri.standard_unit_value else 0,
            "standard_total": float(ri.standard_total) if ri.standard_total else 0,
            "unit_value": float(ri.unit_value) if ri.unit_value else 0,
            "total_value": float(ri.total_value) if ri.total_value else 0,
            "product_id": ri.product_id,
            "product_name": (ri.product.name if ri.product else None) if hasattr(ri, '__dict__') and 'product' in ri.__dict__ else None,
            "is_material": ri.is_material,
            "fulfill_mode": ri.fulfill_mode if hasattr(ri, 'fulfill_mode') else ("material" if ri.is_material else "claim"),
            "advance_payer_type": ri.advance_payer_type,
            "advance_payer_id": ri.advance_payer_id,
            "fulfill_status": ri.fulfill_status,
            "applied_at": str(ri.applied_at) if ri.applied_at else None,
            "fulfilled_at": str(ri.fulfilled_at) if ri.fulfilled_at else None,
            "settled_amount": float(ri.settled_amount) if ri.settled_amount else 0,
            "stock_flow_id": ri.stock_flow_id,
            "fulfilled_qty": ri.fulfilled_qty,
            "arrival_billcode": ri.arrival_billcode,
            "arrival_amount": float(ri.arrival_amount) if ri.arrival_amount else 0,
            "arrival_at": str(ri.arrival_at) if ri.arrival_at else None,
            "voucher_urls": ri.voucher_urls,
            "confirmed_by": ri.confirmed_by,
            "actual_cost": float(ri.actual_cost) if ri.actual_cost else 0,
            "profit_loss": float(ri.profit_loss) if ri.profit_loss else 0,
            "scheme_no": ri.scheme_no, "notes": ri.notes, "sort_order": ri.sort_order,
            "expenses": [],
        }
        try:
            for exp in ri.expenses:
                rid["expenses"].append({
                    "id": exp.id, "name": exp.name,
                    "cost_amount": float(exp.cost_amount), "payer_type": exp.payer_type,
                    "reimburse_amount": float(exp.reimburse_amount),
                    "reimburse_status": exp.reimburse_status,
                    "profit_loss": float(exp.profit_loss),
                })
        except Exception:
            pass  # expenses not loaded yet (e.g. just created)
        d["request_items"].append(rid)
    return d


@router.get("/requests")
async def list_policy_requests(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    status: str | None = Query(None),
    has_items: bool = Query(False, description="只返回有明细项的政策申请"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    from app.models.policy_request_item import PolicyRequestItem

    from app.models.order import Order as _Ord
    from app.core.permissions import is_salesman

    stmt = select(PolicyRequest)
    if brand_id:
        stmt = stmt.where(PolicyRequest.brand_id == brand_id)
    if status:
        stmt = stmt.where(PolicyRequest.status == status)
    if has_items:
        stmt = stmt.where(PolicyRequest.id.in_(
            select(PolicyRequestItem.policy_request_id).distinct()
        ))
    # 业务员只看自己订单的政策
    if is_salesman(user) and user.get("employee_id"):
        stmt = stmt.outerjoin(_Ord, _Ord.id == PolicyRequest.order_id).where(
            (_Ord.salesman_id == user["employee_id"]) | (PolicyRequest.order_id.is_(None))
        )
    stmt = stmt.order_by(PolicyRequest.created_at.desc()).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [_pr_to_response(pr) for pr in rows]


@router.get("/requests/{request_id}")
async def get_policy_request(request_id: str, db: AsyncSession = Depends(get_db)):
    pr = await db.get(PolicyRequest, request_id)
    if pr is None:
        raise HTTPException(404, "PolicyRequest not found")
    return _pr_to_response(pr)


@router.put("/requests/{request_id}")
async def update_policy_request(
    request_id: str, body: PolicyRequestUpdate, db: AsyncSession = Depends(get_db)
):
    pr = await db.get(PolicyRequest, request_id)
    if pr is None:
        raise HTTPException(404, "PolicyRequest not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(pr, k, v)
    await db.flush()
    return _pr_to_response(pr)


@router.delete("/requests/{request_id}", status_code=204)
async def delete_policy_request(
    request_id: str, db: AsyncSession = Depends(get_db)
):
    pr = await db.get(PolicyRequest, request_id)
    if pr is None:
        raise HTTPException(404, "PolicyRequest not found")
    await db.delete(pr)
    await db.flush()


# ═══════════════════════════════════════════════════════════════════
# PolicyUsageRecord CRUD
# ═══════════════════════════════════════════════════════════════════


@router.post(
    "/usage-records", response_model=PolicyUsageRecordResponse, status_code=201
)
async def create_usage_record(
    body: PolicyUsageRecordCreate, db: AsyncSession = Depends(get_db)
):
    rec = PolicyUsageRecord(id=str(uuid.uuid4()), **body.model_dump())
    db.add(rec)
    await db.flush()
    return rec


@router.get("/usage-records", response_model=list[PolicyUsageRecordResponse])
async def list_usage_records(
    user: CurrentUser,
    policy_request_id: str | None = Query(None),
    brand_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(PolicyUsageRecord)
    if policy_request_id:
        stmt = stmt.where(PolicyUsageRecord.policy_request_id == policy_request_id)
    if brand_id:
        stmt = stmt.join(PolicyRequest, PolicyUsageRecord.policy_request_id == PolicyRequest.id).where(PolicyRequest.brand_id == brand_id)
    stmt = stmt.order_by(PolicyUsageRecord.created_at.desc()).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get(
    "/usage-records/{record_id}", response_model=PolicyUsageRecordResponse
)
async def get_usage_record(record_id: str, db: AsyncSession = Depends(get_db)):
    rec = await db.get(PolicyUsageRecord, record_id)
    if rec is None:
        raise HTTPException(404, "PolicyUsageRecord not found")
    return rec


@router.put(
    "/usage-records/{record_id}", response_model=PolicyUsageRecordResponse
)
async def update_usage_record(
    record_id: str,
    body: PolicyUsageRecordUpdate,
    db: AsyncSession = Depends(get_db),
):
    rec = await db.get(PolicyUsageRecord, record_id)
    if rec is None:
        raise HTTPException(404, "PolicyUsageRecord not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(rec, k, v)
    await db.flush()
    return rec


# ═══════════════════════════════════════════════════════════════════
# Material fulfillment — auto outbound from tasting warehouse
# ═══════════════════════════════════════════════════════════════════


class MaterialFulfillItem(BaseModel):
    product_id: str
    quantity: int
    quantity_unit: str = "瓶"  # 箱/瓶，后端按 bpc 换算；库存/扣减始终按瓶
    request_item_id: Optional[str] = None
    barcode: Optional[str] = None  # optional barcode for exact batch matching


class MaterialFulfillRequest(BaseModel):
    items: list[MaterialFulfillItem]


class FulfillItemStatusUpdate(BaseModel):
    request_item_id: str
    fulfill_status: str  # applied / fulfilled / settled
    fulfill_qty: int = 0  # 本次兑付数量（0=全部）
    scheme_no: Optional[str] = None
    actual_cost: Optional[float] = None
    notes: Optional[str] = None


@router.post("/requests/{request_id}/fulfill-materials", status_code=201)
async def fulfill_materials(
    request_id: str, body: MaterialFulfillRequest,
    user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    """Fulfill material items from tasting warehouse + update request_item status."""
    from app.models.inventory import Inventory, StockFlow
    from app.models.policy_request_item import PolicyRequestItem
    from app.models.product import Warehouse
    from app.services.audit_service import log_audit

    pr = await db.get(PolicyRequest, request_id)
    if pr is None:
        raise HTTPException(404, "政策申请不存在")
    if pr.status != "approved":
        raise HTTPException(400, f"政策申请状态为 '{pr.status}'，只有已审批的才能兑付物料")
    if not pr.brand_id:
        raise HTTPException(400, "政策申请没有关联品牌")
    # 订单必须已确认收款（status=completed）才能启动政策兑付
    if pr.order_id:
        from app.models.order import Order as _Ord
        linked_order = await db.get(_Ord, pr.order_id)
        if linked_order and linked_order.status != "completed":
            raise HTTPException(400, f"关联订单 {linked_order.order_no} 状态为 '{linked_order.status}'，需先由财务在审批中心确认收款后才能发起政策兑付")

    wh_result = await db.execute(
        select(Warehouse)
        .where(Warehouse.warehouse_type == "tasting")
        .where(Warehouse.brand_id == pr.brand_id)
        .where(Warehouse.is_active == True)
    )
    tasting_wh = wh_result.scalar_one_or_none()
    if not tasting_wh:
        raise HTTPException(400, "该品牌没有品鉴物料仓库")

    now = datetime.now(timezone.utc)
    results = []
    from app.models.product import Product as _Prod
    for item in body.items:
        if item.quantity <= 0:
            continue
        # 统一换算为瓶数（库存底层按瓶存储）
        bpc = 1
        if item.quantity_unit == '箱':
            prod = await db.get(_Prod, item.product_id)
            bpc = prod.bottles_per_case if prod and prod.bottles_per_case else 1
        bottles = item.quantity * bpc

        # If barcode provided, try exact batch match first
        from app.models.inventory import InventoryBarcode
        barcode_batch = None
        if item.barcode:
            bc = (await db.execute(
                select(InventoryBarcode).where(
                    InventoryBarcode.barcode == item.barcode,
                    InventoryBarcode.product_id == item.product_id,
                    InventoryBarcode.warehouse_id == tasting_wh.id,
                    InventoryBarcode.status == "in_stock",
                )
            )).scalar_one_or_none()
            if bc:
                barcode_batch = bc.batch_no
                bc.status = "outbound"

        inv_query = select(Inventory).where(
            Inventory.product_id == item.product_id,
            Inventory.warehouse_id == tasting_wh.id,
            Inventory.quantity > 0,
        )
        if barcode_batch:
            inv_query = inv_query.order_by(
                (Inventory.batch_no == barcode_batch).desc(),
                Inventory.stock_in_date.asc(),
            )
        else:
            inv_query = inv_query.order_by(Inventory.stock_in_date.asc())
        inv_rows = (await db.execute(inv_query)).scalars().all()

        total_available = sum(r.quantity for r in inv_rows)
        if total_available < bottles:
            prod = await db.get(_Prod, item.product_id)
            raise HTTPException(400, f"品鉴物料仓({tasting_wh.name})库存不足：{prod.name if prod else item.product_id} 需要 {bottles}瓶，可用 {total_available}瓶。")

        remaining = bottles
        for inv in inv_rows:
            if remaining <= 0:
                break
            deduct = min(inv.quantity, remaining)
            inv.quantity -= deduct
            remaining -= deduct

        flow = StockFlow(
            id=str(uuid.uuid4()),
            flow_no=f"SF-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}",
            flow_type="outbound", product_id=item.product_id, warehouse_id=tasting_wh.id,
            batch_no=inv_rows[0].batch_no if inv_rows else "fulfill", quantity=bottles,
            notes=f"政策兑付出库 {pr.id[:8]} ({item.quantity}{item.quantity_unit}={bottles}瓶)",
        )
        db.add(flow)

        # Update linked request_item — track partial fulfillment
        # 按 RequestItem 记录的单位累加 fulfilled_qty
        if item.request_item_id:
            ri = await db.get(PolicyRequestItem, item.request_item_id)
            if ri:
                # ri.quantity_unit=瓶时加瓶数，=箱时加箱数
                inc = bottles if ri.quantity_unit == '瓶' else item.quantity
                ri.fulfilled_qty = (ri.fulfilled_qty or 0) + inc
                ri.stock_flow_id = flow.id
                if ri.fulfilled_qty >= ri.quantity:
                    ri.fulfill_status = "fulfilled"
                    ri.fulfilled_at = now
                    await _trigger_advance_refund_if_fulfilled(db, ri)
                else:
                    ri.fulfill_status = "applied"

        results.append({"product_id": item.product_id, "bottles": bottles, "flow_id": flow.id})

    await db.flush()
    await log_audit(db, action="fulfill_materials", entity_type="PolicyRequest", entity_id=pr.id,
                    changes={"items": [{"product_id": r["product_id"], "bottles": r["bottles"]} for r in results]}, user=user)
    return {"detail": f"兑付完成，共出库 {len(results)} 种物料", "flows": results}


@router.post("/requests/{request_id}/fulfill-item-status", status_code=200)
async def update_fulfill_item_status(
    request_id: str, body: FulfillItemStatusUpdate,
    user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    """Update a single request item's fulfill status (for non-material items like meals, travel, rebates)."""
    from app.models.policy_request_item import PolicyRequestItem
    from app.services.audit_service import log_audit

    pr = await db.get(PolicyRequest, request_id)
    if pr is None:
        raise HTTPException(404, "政策申请不存在")
    # 订单必须已确认收款（status=completed）才能启动政策兑付
    if pr.order_id:
        from app.models.order import Order as _Ord
        linked_order = await db.get(_Ord, pr.order_id)
        if linked_order and linked_order.status != "completed":
            raise HTTPException(400, f"关联订单 {linked_order.order_no} 状态为 '{linked_order.status}'，需先确认收款后才能发起政策兑付")

    ri = await db.get(PolicyRequestItem, body.request_item_id)
    if ri is None or ri.policy_request_id != request_id:
        raise HTTPException(404, "政策明细项不存在")

    now = datetime.now(timezone.utc)

    # 处理逐次兑付：不管当前什么状态，只要有剩余数量就能继续申请
    remaining = ri.quantity - ri.fulfilled_qty
    if body.fulfill_qty > 0 and body.fulfill_status == "applied":
        if body.fulfill_qty > remaining:
            raise HTTPException(400, f"本次兑付 {body.fulfill_qty} 超过剩余 {remaining}")
        ri.fulfilled_qty += body.fulfill_qty
        ri.applied_at = now
        # 状态设为applied（即使之前是settled/arrived，因为新一批又开始了）
        ri.fulfill_status = "applied"
    elif body.fulfill_status == "applied" and body.fulfill_qty <= 0:
        # 不指定数量 = 全部剩余
        ri.fulfilled_qty = ri.quantity
        ri.applied_at = now
        ri.fulfill_status = "applied"
    elif body.fulfill_status == "fulfilled":
        ri.fulfill_status = "fulfilled"
        ri.fulfilled_at = now
        await _trigger_advance_refund_if_fulfilled(db, ri)
    else:
        ri.fulfill_status = body.fulfill_status

    if body.scheme_no is not None:
        ri.scheme_no = body.scheme_no
    if body.actual_cost is not None:
        cost = Decimal(str(body.actual_cost))
        ri.actual_cost += cost
        ri.profit_loss = ri.standard_total - ri.total_value - ri.actual_cost

        # F类报账：实际花费从总资金池扣款
        if pr.request_source == "f_class" and cost > 0:
            from app.models.product import Account
            from app.api.routes.accounts import record_fund_flow
            master_acc = (await db.execute(
                select(Account).where(Account.level == "master")
            )).scalar_one_or_none()
            if master_acc and master_acc.balance >= cost:
                master_acc.balance -= cost
                await record_fund_flow(
                    db, account_id=master_acc.id, flow_type='debit', amount=cost,
                    balance_after=master_acc.balance, related_type='f_class_expense',
                    related_id=ri.id, notes=f"F类报账垫付: {ri.name}",
                )
    if body.notes is not None:
        # 追加备注而不是覆盖
        if ri.notes:
            ri.notes = ri.notes + f"\n[{now.strftime('%m-%d')}] {body.notes}"
        else:
            ri.notes = body.notes

    await db.flush()
    await log_audit(db, action="update_fulfill_status", entity_type="PolicyRequestItem", entity_id=ri.id,
                    changes={"status": ri.fulfill_status, "fulfilled_qty": ri.fulfilled_qty}, user=user)
    return {"detail": f"已兑付 {ri.fulfilled_qty}/{ri.quantity}", "item_id": ri.id}


# ═══════════════════════════════════════════════════════════════════
# PolicyItemExpense CRUD — expenses linked to a policy item
# ═══════════════════════════════════════════════════════════════════


class ExpenseItemCreate(BaseModel):
    name: str
    cost_amount: float = 0
    payer_type: Optional[str] = None
    payer_id: Optional[str] = None
    reimburse_amount: float = 0
    voucher_url: Optional[str] = None
    notes: Optional[str] = None


class ExpenseItemResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    request_item_id: str
    name: str
    cost_amount: float
    payer_type: Optional[str] = None
    payer_id: Optional[str] = None
    reimburse_amount: float
    reimburse_status: str = "pending"
    profit_loss: float = 0
    voucher_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None


@router.post("/request-items/{item_id}/expenses", status_code=201)
async def create_item_expense(
    item_id: str, body: ExpenseItemCreate,
    user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    from app.models.policy_item_expense import PolicyItemExpense
    from app.models.policy_request_item import PolicyRequestItem

    ri = await db.get(PolicyRequestItem, item_id)
    if ri is None:
        raise HTTPException(404, "政策明细项不存在")

    cost = Decimal(str(body.cost_amount))
    reimburse = Decimal(str(body.reimburse_amount))
    expense = PolicyItemExpense(
        id=str(uuid.uuid4()),
        request_item_id=item_id,
        name=body.name,
        cost_amount=cost,
        payer_type=body.payer_type,
        payer_id=body.payer_id,
        reimburse_amount=reimburse,
        profit_loss=reimburse - cost,
        voucher_url=body.voucher_url,
        notes=body.notes,
    )
    db.add(expense)
    await db.flush()
    return expense


@router.get("/request-items/{item_id}/expenses", response_model=list[ExpenseItemResponse])
async def list_item_expenses(item_id: str, db: AsyncSession = Depends(get_db)):
    from app.models.policy_item_expense import PolicyItemExpense
    rows = (await db.execute(
        select(PolicyItemExpense).where(PolicyItemExpense.request_item_id == item_id)
        .order_by(PolicyItemExpense.created_at)
    )).scalars().all()
    return rows


@router.put("/expenses/{expense_id}", response_model=ExpenseItemResponse)
async def update_item_expense(
    expense_id: str, body: ExpenseItemCreate,
    user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    from app.models.policy_item_expense import PolicyItemExpense
    exp = await db.get(PolicyItemExpense, expense_id)
    if exp is None:
        raise HTTPException(404, "费用记录不存在")
    exp.name = body.name
    exp.cost_amount = Decimal(str(body.cost_amount))
    exp.payer_type = body.payer_type
    exp.payer_id = body.payer_id
    exp.reimburse_amount = Decimal(str(body.reimburse_amount))
    exp.profit_loss = exp.reimburse_amount - exp.cost_amount
    exp.voucher_url = body.voucher_url
    exp.notes = body.notes
    await db.flush()
    return exp


@router.delete("/expenses/{expense_id}", status_code=204)
async def delete_item_expense(expense_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    from app.models.policy_item_expense import PolicyItemExpense
    exp = await db.get(PolicyItemExpense, expense_id)
    if exp is None:
        raise HTTPException(404, "费用记录不存在")
    await db.delete(exp)
    await db.flush()


# ═══════════════════════════════════════════════════════════════════
# Arrival matching — import manufacturer Excel, match by scheme_no
# ═══════════════════════════════════════════════════════════════════


@router.post("/requests/match-arrival")
async def match_arrival_excel(
    file: UploadFile,
    user: CurrentUser,
    brand_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Parse manufacturer arrival Excel, match rows to PolicyRequestItem.scheme_no."""
    from app.models.policy_request_item import PolicyRequestItem
    import io

    content = await file.read()
    rows = []
    try:
        import xlrd
        wb = xlrd.open_workbook(file_contents=content)
        ws = wb.sheet_by_index(0)
        for i in range(2, ws.nrows):  # skip header rows
            billcode = str(ws.cell_value(i, 1)).strip()
            pronumber = str(ws.cell_value(i, 2)).strip()
            memo = str(ws.cell_value(i, 7)).strip()
            income = ws.cell_value(i, 8)
            if not billcode and not pronumber:
                continue
            rows.append({"billcode": billcode, "pronumber": pronumber, "memo": memo, "income": float(income) if income else 0})
    except Exception:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
            ws = wb.active
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i < 2: continue
                billcode = str(row[1] or '').strip()
                pronumber = str(row[2] or '').strip()
                memo = str(row[7] or '').strip() if len(row) > 7 else ''
                income = float(row[8]) if len(row) > 8 and row[8] else 0
                if not billcode and not pronumber:
                    continue
                rows.append({"billcode": billcode, "pronumber": pronumber, "memo": memo, "income": income})
        except Exception as e:
            raise HTTPException(400, f"无法解析Excel文件: {e}")

    # Fetch all applied items for this brand
    stmt = (
        select(PolicyRequestItem)
        .join(PolicyRequest, PolicyRequestItem.policy_request_id == PolicyRequest.id)
        .where(PolicyRequest.brand_id == brand_id)
        .where(PolicyRequestItem.fulfill_status == "applied")
        .where(PolicyRequestItem.scheme_no.isnot(None))
    )
    items = (await db.execute(stmt)).scalars().all()
    item_by_scheme: dict[str, list] = {}
    for it in items:
        if it.scheme_no:
            item_by_scheme.setdefault(it.scheme_no, []).append(it)

    # Preload 工资补贴应收（按 period 聚合），用于第二轮匹配
    from app.models.payroll import ManufacturerSalarySubsidy
    from datetime import datetime as _dt
    import re
    sub_rows = (await db.execute(
        select(ManufacturerSalarySubsidy).where(
            ManufacturerSalarySubsidy.brand_id == brand_id,
            ManufacturerSalarySubsidy.status.in_(('pending', 'advanced')),
        )
    )).scalars().all()
    sub_by_period: dict[str, Decimal] = {}
    for s in sub_rows:
        sub_by_period[s.period] = sub_by_period.get(s.period, Decimal("0")) + s.subsidy_amount
    used_periods: set[str] = set()

    def _parse_period(text: str) -> Optional[str]:
        text = text or ""
        m = re.search(r"(20\d{2})[-/.年 ]?(\d{1,2})", text)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}"
        m = re.search(r"(\d{1,2})\s*月", text)
        if m:
            return f"{_dt.now().year}-{int(m.group(1)):02d}"
        return None

    # Match
    matched = []
    salary_matched = []
    unmatched = []
    for row in rows:
        if row["income"] <= 0:
            continue
        # 第一轮：政策 scheme_no
        found = None
        if row["pronumber"] and row["pronumber"] in item_by_scheme:
            candidates = item_by_scheme[row["pronumber"]]
            if candidates:
                found = candidates[0]
                candidates.pop(0)
        if found:
            matched.append({
                "item_id": found.id,
                "item_name": found.name,
                "benefit_type": found.benefit_type,
                "scheme_no": found.scheme_no,
                "billcode": row["billcode"],
                "memo": row["memo"],
                "income": row["income"],
            })
            continue

        # 第二轮：工资补贴 品牌+周期+金额
        period = _parse_period(row["memo"]) or _parse_period(row["billcode"])
        if period and period not in used_periods:
            expected = sub_by_period.get(period)
            if expected is not None and Decimal(str(row["income"])) == expected:
                used_periods.add(period)
                salary_matched.append({
                    "brand_id": brand_id,
                    "period": period,
                    "billcode": row["billcode"],
                    "memo": row["memo"],
                    "income": row["income"],
                    "expected_amount": float(expected),
                })
                continue

        unmatched.append({
            "billcode": row["billcode"],
            "pronumber": row["pronumber"],
            "memo": row["memo"],
            "income": row["income"],
        })

    return {
        "matched": matched,
        "salary_matched": salary_matched,
        "unmatched": unmatched,
        "total_rows": len(rows),
    }


class ArrivalConfirmItem(BaseModel):
    item_id: str
    arrived_amount: float
    billcode: Optional[str] = None


class SalaryArrivalConfirm(BaseModel):
    brand_id: str
    period: str
    arrived_amount: float
    billcode: Optional[str] = None


class ArrivalConfirmRequest(BaseModel):
    items: list[ArrivalConfirmItem] = []
    salary_items: list[SalaryArrivalConfirm] = []


@router.post("/requests/confirm-arrival")
async def confirm_arrival(
    body: ArrivalConfirmRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Batch mark items as arrived (厂家已到账)."""
    from app.models.policy_request_item import PolicyRequestItem

    now = datetime.now(timezone.utc)
    updated = 0
    for item in body.items:
        ri = await db.get(PolicyRequestItem, item.item_id)
        if ri is None:
            continue
        ri.fulfill_status = "arrived"
        ri.arrival_amount = Decimal(str(item.arrived_amount))
        ri.arrival_billcode = item.billcode
        ri.arrival_at = now
        updated += 1

        # F类报账到账：钱进F类账户
        pr = await db.get(PolicyRequest, ri.policy_request_id)
        if pr and pr.request_source == "f_class" and pr.brand_id and item.arrived_amount > 0:
            from app.models.product import Account
            from app.api.routes.accounts import record_fund_flow
            f_acc = (await db.execute(
                select(Account).where(
                    Account.brand_id == pr.brand_id,
                    Account.account_type == "f_class",
                    Account.level == "project",
                )
            )).scalar_one_or_none()
            if not f_acc:
                raise HTTPException(400, f"品牌未配置 F类账户，无法记录到账金额 ¥{item.arrived_amount}。请先到「账户管理」创建该品牌的 F类项目账户。")
            amt = Decimal(str(item.arrived_amount))
            f_acc.balance += amt
            await record_fund_flow(
                db, account_id=f_acc.id, flow_type='credit', amount=amt,
                balance_after=f_acc.balance, related_type='f_class_arrival',
                related_id=ri.id, notes=f"F类报账到账: {ri.name} 单据{item.billcode or '-'}",
            )

    # 工资补贴到账：聚合该品牌该期应收（pending+advanced），金额必须严格相等
    salary_updated = 0
    if body.salary_items:
        from app.models.payroll import ManufacturerSalarySubsidy
        from app.models.product import Account as _Acct
        from app.api.routes.accounts import record_fund_flow as _rff
        for si in body.salary_items:
            subs = (await db.execute(
                select(ManufacturerSalarySubsidy).where(
                    ManufacturerSalarySubsidy.brand_id == si.brand_id,
                    ManufacturerSalarySubsidy.period == si.period,
                    ManufacturerSalarySubsidy.status.in_(('pending', 'advanced')),
                )
            )).scalars().all()
            if not subs:
                raise HTTPException(400, f"{si.period} 无待到账工资补贴")
            total = sum((s.subsidy_amount for s in subs), Decimal("0"))
            arrived = Decimal(str(si.arrived_amount))
            if arrived != total:
                raise HTTPException(400, f"{si.period} 工资补贴应收 ¥{total}，到账 ¥{arrived} 不匹配")
            cash_acc = (await db.execute(
                select(_Acct).where(
                    _Acct.brand_id == si.brand_id,
                    _Acct.account_type == "cash",
                    _Acct.level == "project",
                )
            )).scalar_one_or_none()
            if not cash_acc:
                raise HTTPException(400, "品牌未配置现金账户")
            cash_acc.balance += total
            await _rff(
                db, account_id=cash_acc.id, flow_type='credit', amount=total,
                balance_after=cash_acc.balance, related_type='manufacturer_salary_arrival',
                notes=f"厂家工资补贴到账 {si.period} 单据 {si.billcode or '-'}",
            )
            for s in subs:
                s.status = 'reimbursed'
                s.arrival_at = now
                s.arrival_billcode = si.billcode
                s.reimbursed_at = now
                s.reimburse_account_id = cash_acc.id
                salary_updated += 1

    await db.flush()
    return {"detail": f"已标记 {updated} 项政策到账，{salary_updated} 条工资补贴核销", "updated": updated, "salary_updated": salary_updated}


class FulfillVoucherBody(BaseModel):
    item_id: str
    voucher_urls: list[str]


@router.post("/requests/{request_id}/submit-voucher")
async def submit_fulfill_voucher(
    request_id: str, body: FulfillVoucherBody,
    user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    """arrived → fulfilled: upload voucher for fulfillment to advance payer."""
    from app.models.policy_request_item import PolicyRequestItem

    ri = await db.get(PolicyRequestItem, body.item_id)
    if ri is None or ri.policy_request_id != request_id:
        raise HTTPException(404, "政策明细项不存在")
    if ri.fulfill_status not in ("arrived", "settled", "fulfilled"):
        raise HTTPException(400, f"状态为 '{ri.fulfill_status}'，需要先到账确认才能提交兑付凭证")

    # Append voucher urls
    existing = ri.voucher_urls or []
    ri.voucher_urls = existing + body.voucher_urls
    ri.fulfill_status = "fulfilled"
    ri.fulfilled_at = datetime.now(timezone.utc)
    await db.flush()
    return {"detail": "兑付凭证已提交，等待财务确认"}


class ConfirmFulfillBody(BaseModel):
    item_id: str


@router.post("/requests/{request_id}/confirm-fulfill")
async def confirm_fulfill(
    request_id: str, body: ConfirmFulfillBody,
    user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    """fulfilled → settled: finance confirms fulfillment, archive."""
    from app.models.policy_request_item import PolicyRequestItem

    ri = await db.get(PolicyRequestItem, body.item_id)
    if ri is None or ri.policy_request_id != request_id:
        raise HTTPException(404, "政策明细项不存在")
    if ri.fulfill_status not in ("fulfilled", "settled"):
        raise HTTPException(400, f"状态为 '{ri.fulfill_status}'，需要先提交兑付凭证")

    # 确认后归档。如果还有剩余数量，业务员在政策申请页继续申请时会重新激活状态
    ri.fulfill_status = "settled"
    ri.settled_amount = (ri.settled_amount or Decimal("0")) + (ri.arrival_amount or ri.total_value)
    ri.confirmed_by = user.get("employee_id")
    await db.flush()
    await log_audit(db, action="confirm_fulfill", entity_type="PolicyRequestItem", entity_id=ri.id, user=user)
    return {"detail": "已确认归档"}


# ═══════════════════════════════════════════════════════════════════
# PolicyClaim CRUD
# ═══════════════════════════════════════════════════════════════════


@router.post("/claims", response_model=PolicyClaimResponse, status_code=201)
async def create_policy_claim(
    body: PolicyClaimCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    from app.models.policy_request_item import PolicyRequestItem

    data = body.model_dump(exclude={"items"})
    claim = PolicyClaim(
        id=str(uuid.uuid4()),
        claim_no=_generate_claim_no(),
        **data,
    )

    # ── Validate claim items against PolicyRequestItem ─────────────
    total_declared = Decimal("0.00")
    for it in body.items:
        # Support new source_request_item_id path
        if it.source_request_item_id:
            ri = await db.get(PolicyRequestItem, it.source_request_item_id)
            if ri is None:
                raise HTTPException(404, f"政策明细项 {it.source_request_item_id} 不存在")

            # Validate: cumulative declared must not exceed item total_value
            existing_sum = (
                await db.execute(
                    select(func.coalesce(func.sum(PolicyClaimItem.declared_amount), 0))
                    .where(PolicyClaimItem.source_request_item_id == it.source_request_item_id)
                )
            ).scalar_one()
            total_for_item = Decimal(str(existing_sum)) + it.declared_amount
            if total_for_item > ri.total_value:
                raise HTTPException(
                    400,
                    f"累计申报金额 {total_for_item} 超过政策明细项价值 {ri.total_value}",
                )

        elif it.source_usage_record_id:
            # Legacy path: validate via PolicyUsageRecord
            usage = await db.get(PolicyUsageRecord, it.source_usage_record_id)
            if usage is None:
                raise HTTPException(404, f"PolicyUsageRecord {it.source_usage_record_id} not found")
            existing_sum = (
                await db.execute(
                    select(func.coalesce(func.sum(PolicyClaimItem.declared_amount), 0))
                    .where(PolicyClaimItem.source_usage_record_id == it.source_usage_record_id)
                )
            ).scalar_one()
            total_for_item = Decimal(str(existing_sum)) + it.declared_amount
            if total_for_item > usage.reimbursement_amount:
                raise HTTPException(400, f"累计申报金额超过可报销金额")

        ci = PolicyClaimItem(
            id=str(uuid.uuid4()),
            claim_id=claim.id,
            **it.model_dump(),
        )
        claim.items.append(ci)
        total_declared += it.declared_amount

    claim.claim_amount = total_declared
    claim.unsettled_amount = total_declared
    db.add(claim)
    await db.flush()
    await log_audit(db, action="create_claim", entity_type="PolicyClaim", entity_id=claim.id, user=user)
    return claim


@router.get("/claims", response_model=list[PolicyClaimResponse])
async def list_policy_claims(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(PolicyClaim)
        .options(selectinload(PolicyClaim.items))
    )
    if brand_id:
        stmt = stmt.where(PolicyClaim.brand_id == brand_id)
    stmt = stmt.order_by(PolicyClaim.created_at.desc()).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/claims/{claim_id}", response_model=PolicyClaimResponse)
async def get_policy_claim(claim_id: str, db: AsyncSession = Depends(get_db)):
    claim = (
        await db.execute(
            select(PolicyClaim)
            .where(PolicyClaim.id == claim_id)
            .options(selectinload(PolicyClaim.items))
        )
    ).scalar_one_or_none()
    if claim is None:
        raise HTTPException(404, "PolicyClaim not found")
    return claim


@router.put("/claims/{claim_id}", response_model=PolicyClaimResponse)
async def update_policy_claim(
    claim_id: str, body: PolicyClaimUpdate, db: AsyncSession = Depends(get_db)
):
    claim = await db.get(PolicyClaim, claim_id)
    if claim is None:
        raise HTTPException(404, "PolicyClaim not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(claim, k, v)
    await db.flush()
    return claim


@router.delete("/claims/{claim_id}", status_code=204)
async def delete_policy_claim(claim_id: str, db: AsyncSession = Depends(get_db)):
    claim = await db.get(PolicyClaim, claim_id)
    if claim is None:
        raise HTTPException(404, "PolicyClaim not found")
    await db.delete(claim)
    await db.flush()
