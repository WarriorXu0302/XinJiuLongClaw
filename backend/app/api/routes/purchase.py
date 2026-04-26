"""
Purchase Order API — CRUD + approval + receive.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, Optional

from app.core.database import get_db
from app.core.permissions import apply_data_scope, require_role
from app.core.security import CurrentUser
from app.models.base import PurchaseStatus
from app.models.inventory import Inventory, StockFlow
from app.models.product import Account, Warehouse
from app.models.purchase import PurchaseOrder, PurchaseOrderItem
from app.services.audit_service import log_audit

router = APIRouter()


def _gen_no(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"{prefix}-{ts}-{short}"


# ═══════════════════════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════════════════════


class POItemCreate(BaseModel):
    product_id: str
    quantity: int
    quantity_unit: str = "箱"
    unit_price: float = 0


from datetime import date as date_type

class POCreate(BaseModel):
    brand_id: str
    supplier_id: str
    warehouse_id: str
    cash_amount: float = 0
    f_class_amount: float = 0
    financing_amount: float = 0
    cash_account_id: Optional[str] = None
    f_class_account_id: Optional[str] = None
    financing_account_id: Optional[str] = None
    voucher_url: Optional[str] = None
    expected_date: Optional[date_type] = None
    notes: Optional[str] = None
    items: list[POItemCreate] = []


class POItemResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    product_id: str
    product_name: Optional[str] = None
    product: Optional[Any] = None
    quantity: int
    quantity_unit: str = "箱"
    unit_price: float


class POResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    po_no: str
    brand_id: Optional[str] = None
    brand_name: Optional[str] = None
    supplier_id: str
    supplier_name: Optional[str] = None
    supplier: Optional[Any] = None
    warehouse_id: Optional[str] = None
    warehouse: Optional[Any] = None
    total_amount: float
    cash_amount: float
    f_class_amount: float
    financing_amount: float = 0
    voucher_url: Optional[str] = None
    status: str
    expected_date: Optional[date_type] = None
    notes: Optional[str] = None
    created_at: datetime
    items: list[POItemResponse] = []


# ═══════════════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════════════


@router.post("", response_model=POResponse, status_code=201)
async def create_purchase_order(body: POCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Create PO (status=pending). Does NOT deduct money yet."""
    require_role(user, "boss", "purchase", "warehouse")
    total = Decimal("0")
    po = PurchaseOrder(
        id=str(uuid.uuid4()),
        po_no=_gen_no("PO"),
        brand_id=body.brand_id,
        supplier_id=body.supplier_id,
        warehouse_id=body.warehouse_id,
        cash_amount=Decimal(str(body.cash_amount)),
        f_class_amount=Decimal(str(body.f_class_amount)),
        financing_amount=Decimal(str(body.financing_amount)),
        cash_account_id=body.cash_account_id,
        f_class_account_id=body.f_class_account_id,
        financing_account_id=body.financing_account_id,
        voucher_url=body.voucher_url,
        expected_date=body.expected_date,
        notes=body.notes,
    )
    for it in body.items:
        poi = PurchaseOrderItem(
            id=str(uuid.uuid4()), po_id=po.id,
            product_id=it.product_id, quantity=it.quantity,
            quantity_unit=it.quantity_unit,
            unit_price=Decimal(str(it.unit_price)),
        )
        po.items.append(poi)
        total += Decimal(str(it.unit_price)) * it.quantity

    po.total_amount = total

    # Validate payment equals total exactly (skip for tasting warehouse — no payment needed)
    wh = await db.get(Warehouse, body.warehouse_id) if body.warehouse_id else None
    is_tasting = wh and wh.warehouse_type == 'tasting'
    if not is_tasting:
        pay_sum = po.cash_amount + po.f_class_amount + po.financing_amount
        if pay_sum < total:
            raise HTTPException(400, f"付款金额 ¥{pay_sum} 不足以覆盖总金额 ¥{total}")
        if pay_sum > total:
            raise HTTPException(400, f"付款金额 ¥{pay_sum} 超过总金额 ¥{total}，请调整")
    else:
        po.total_amount = Decimal("0")  # tasting warehouse: no monetary value
        # 仍需走审批流程，status保持pending

    db.add(po)
    await db.flush()
    await db.refresh(po, ["items", "supplier", "warehouse", "brand"])
    await log_audit(db, action="create_purchase_order", entity_type="PurchaseOrder", entity_id=po.id, user=user)
    return _po_to_response(po)


def _po_to_response(po: PurchaseOrder) -> dict:
    """Convert PurchaseOrder ORM to response dict with nested names."""
    d = POResponse.model_validate(po).model_dump()
    d["supplier_name"] = po.supplier.name if po.supplier else None
    d["supplier"] = {"name": po.supplier.name} if po.supplier else None
    d["brand_name"] = po.brand.name if po.brand else None
    d["warehouse"] = {"name": po.warehouse.name, "warehouse_type": po.warehouse.warehouse_type} if po.warehouse else None
    d["items"] = []
    for item in po.items:
        item_d = POItemResponse.model_validate(item).model_dump()
        if item.product:
            item_d["product_name"] = item.product.name
            item_d["product"] = {"name": item.product.name, "bottles_per_case": item.product.bottles_per_case}
        d["items"].append(item_d)
    return d


@router.get("")
async def list_purchase_orders(
    user: CurrentUser,
    brand_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    base = select(PurchaseOrder)
    if brand_id:
        base = base.where(PurchaseOrder.brand_id == brand_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    rows = (await db.execute(base.order_by(PurchaseOrder.created_at.desc()).offset(skip).limit(limit))).scalars().all()
    return {"items": [_po_to_response(po) for po in rows], "total": total}


@router.get("/{po_id}", response_model=POResponse)
async def get_purchase_order(po_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    obj = await db.get(PurchaseOrder, po_id)
    if obj is None:
        raise HTTPException(404, "PurchaseOrder not found")
    return _po_to_response(obj)


# ═══════════════════════════════════════════════════════════════════
# Approval: approve → deduct money + record fund flows
# ═══════════════════════════════════════════════════════════════════


@router.post("/{po_id}/approve")
async def approve_purchase_order(po_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Approve PO → deduct from brand accounts → status=paid."""
    require_role(user, "boss", "finance")
    po = await db.get(PurchaseOrder, po_id)
    if po is None:
        raise HTTPException(404, "PurchaseOrder not found")
    if po.status != PurchaseStatus.PENDING:
        raise HTTPException(400, f"采购单状态为 '{po.status}'，只有 pending 可审批")

    # 品鉴物料仓：审批通过但不扣款
    wh = await db.get(Warehouse, po.warehouse_id) if po.warehouse_id else None
    is_tasting = wh and wh.warehouse_type == 'tasting'
    if is_tasting:
        po.status = PurchaseStatus.PAID
        po.approved_by = user.get('employee_id')
        await db.flush()
        await log_audit(db, action="approve_purchase_order", entity_type="PurchaseOrder", entity_id=po.id,
                        changes={"tasting_warehouse": True}, user=user)
        return {"message": f"品鉴物料采购单 {po.po_no} 审批通过，可扫码收货入库", "status": "paid"}

    from app.api.routes.accounts import record_fund_flow

    # Deduct from cash account
    if po.cash_amount > 0 and po.cash_account_id:
        cash_acc = await db.get(Account, po.cash_account_id)
        if not cash_acc:
            raise HTTPException(400, "现金付款账户不存在")
        if cash_acc.balance < po.cash_amount:
            raise HTTPException(400, f"现金账户余额不足：{cash_acc.name} 余额 ¥{cash_acc.balance}，需付 ¥{po.cash_amount}")
        cash_acc.balance -= po.cash_amount
        await record_fund_flow(
            db, account_id=cash_acc.id, flow_type='debit', amount=po.cash_amount,
            balance_after=cash_acc.balance, related_type='purchase', related_id=po.id,
            notes=f"采购付款(现金) {po.po_no}", created_by=user.get('employee_id'),
        )

    # Deduct from F-class account
    if po.f_class_amount > 0 and po.f_class_account_id:
        f_acc = await db.get(Account, po.f_class_account_id)
        if not f_acc:
            raise HTTPException(400, "F类付款账户不存在")
        if f_acc.balance < po.f_class_amount:
            raise HTTPException(400, f"F类账户余额不足：{f_acc.name} 余额 ¥{f_acc.balance}，需付 ¥{po.f_class_amount}")
        f_acc.balance -= po.f_class_amount
        await record_fund_flow(
            db, account_id=f_acc.id, flow_type='debit', amount=po.f_class_amount,
            balance_after=f_acc.balance, related_type='purchase', related_id=po.id,
            notes=f"采购付款(F类) {po.po_no}", created_by=user.get('employee_id'),
        )

    # Deduct from financing account
    if po.financing_amount > 0 and po.financing_account_id:
        fin_acc = await db.get(Account, po.financing_account_id)
        if not fin_acc:
            raise HTTPException(400, "融资付款账户不存在")
        if fin_acc.balance < po.financing_amount:
            raise HTTPException(400, f"融资账户余额不足：{fin_acc.name} 余额 ¥{fin_acc.balance}，需付 ¥{po.financing_amount}")
        fin_acc.balance -= po.financing_amount
        await record_fund_flow(
            db, account_id=fin_acc.id, flow_type='debit', amount=po.financing_amount,
            balance_after=fin_acc.balance, related_type='purchase', related_id=po.id,
            notes=f"采购付款(融资) {po.po_no}", created_by=user.get('employee_id'),
        )

    # 累加回款账户（现金+融资=回款金额）
    payment_total = po.cash_amount + po.financing_amount
    if payment_total > 0 and po.brand_id:
        ptm_acc = (await db.execute(
            select(Account).where(Account.brand_id == po.brand_id, Account.account_type == 'payment_to_mfr')
        )).scalar_one_or_none()
        if ptm_acc:
            ptm_acc.balance += payment_total
            await record_fund_flow(
                db, account_id=ptm_acc.id, flow_type='credit', amount=payment_total,
                balance_after=ptm_acc.balance, related_type='purchase_payment', related_id=po.id,
                notes=f"采购回款 {po.po_no} (现金{po.cash_amount}+融资{po.financing_amount})",
            )

    po.status = PurchaseStatus.PAID
    po.approved_by = user.get('employee_id')
    await db.flush()
    await log_audit(db, action="approve_purchase_order", entity_type="PurchaseOrder", entity_id=po.id,
                    changes={"cash": float(po.cash_amount), "f_class": float(po.f_class_amount)}, user=user)
    return {"message": f"采购单 {po.po_no} 审批通过，已从账户扣款", "status": "paid"}


@router.post("/{po_id}/reject")
async def reject_purchase_order(po_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_role(user, "boss", "finance")
    po = await db.get(PurchaseOrder, po_id)
    if po is None:
        raise HTTPException(404, "PurchaseOrder not found")
    if po.status != PurchaseStatus.PENDING:
        raise HTTPException(400, f"采购单状态为 '{po.status}'，只有 pending 可驳回")
    po.status = PurchaseStatus.CANCELLED
    await db.flush()
    return {"message": "采购单已驳回"}


@router.post("/{po_id}/cancel")
async def cancel_paid_purchase_order(po_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """已付款但未收货的采购单撤销：反转账户变动 + 状态改为 cancelled。"""
    require_role(user, "boss", "purchase")
    po = await db.get(PurchaseOrder, po_id)
    if po is None:
        raise HTTPException(404, "PurchaseOrder not found")
    if po.status != PurchaseStatus.PAID:
        raise HTTPException(400, f"采购单状态为 '{po.status}'，只有 paid（已付款未收货）可撤销；已收货请走退货流程")

    from app.api.routes.accounts import record_fund_flow

    # 退还现金账户
    if po.cash_amount > 0 and po.cash_account_id:
        cash_acc = await db.get(Account, po.cash_account_id)
        if cash_acc:
            cash_acc.balance += po.cash_amount
            await record_fund_flow(db, account_id=cash_acc.id, flow_type='credit', amount=po.cash_amount,
                balance_after=cash_acc.balance, related_type='purchase_cancel', related_id=po.id,
                notes=f"撤销采购付款(现金) {po.po_no}")
    # 退还F类账户
    if po.f_class_amount > 0 and po.f_class_account_id:
        f_acc = await db.get(Account, po.f_class_account_id)
        if f_acc:
            f_acc.balance += po.f_class_amount
            await record_fund_flow(db, account_id=f_acc.id, flow_type='credit', amount=po.f_class_amount,
                balance_after=f_acc.balance, related_type='purchase_cancel', related_id=po.id,
                notes=f"撤销采购付款(F类) {po.po_no}")
    # 退还融资账户
    if po.financing_amount > 0 and po.financing_account_id:
        fin_acc = await db.get(Account, po.financing_account_id)
        if fin_acc:
            fin_acc.balance += po.financing_amount
            await record_fund_flow(db, account_id=fin_acc.id, flow_type='credit', amount=po.financing_amount,
                balance_after=fin_acc.balance, related_type='purchase_cancel', related_id=po.id,
                notes=f"撤销采购付款(融资) {po.po_no}")
    # 撤销回款账户减少（payment_to_mfr 代表"已应付给厂家"的记账，撤销时反扣）
    # 用 SELECT FOR UPDATE 锁行 + 余额校验，防并发撤销多个 PO 导致账户变负
    payment_total = po.cash_amount + po.financing_amount
    if payment_total > 0 and po.brand_id:
        ptm_acc = (await db.execute(
            select(Account)
            .where(Account.brand_id == po.brand_id, Account.account_type == 'payment_to_mfr')
            .with_for_update()
        )).scalar_one_or_none()
        if ptm_acc:
            if Decimal(str(ptm_acc.balance)) < Decimal(str(payment_total)):
                raise HTTPException(
                    400,
                    f"回款账户 {ptm_acc.name} 余额不足 "
                    f"(¥{ptm_acc.balance} < ¥{payment_total})，无法撤销。"
                    "可能有并发操作或之前已部分结算，请联系财务核对。",
                )
            ptm_acc.balance -= payment_total
            await record_fund_flow(db, account_id=ptm_acc.id, flow_type='debit', amount=payment_total,
                balance_after=ptm_acc.balance, related_type='purchase_cancel', related_id=po.id,
                notes=f"撤销采购回款 {po.po_no}")

    po.status = PurchaseStatus.CANCELLED
    await db.flush()
    await log_audit(db, action="cancel_purchase_order", entity_type="PurchaseOrder", entity_id=po.id, user=user)
    return {"message": f"采购单 {po.po_no} 已撤销，款项已退回"}


# ═══════════════════════════════════════════════════════════════════
# Receive: paid → received (stock in)
# ═══════════════════════════════════════════════════════════════════


@router.post("/{po_id}/receive", response_model=POResponse)
async def receive_purchase_order(
    po_id: str, user: CurrentUser,
    batch_no: str = Query(..., description="入库批次号"),
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "warehouse", "purchase")
    po = await db.get(PurchaseOrder, po_id)
    if po is None:
        raise HTTPException(404, "PurchaseOrder not found")
    if po.status in (PurchaseStatus.RECEIVED, PurchaseStatus.COMPLETED):
        raise HTTPException(400, f"采购单已收货，状态: {po.status}")

    # Normal PO must be paid first; tasting warehouse auto-approved so always ok
    wh = await db.get(Warehouse, po.warehouse_id) if po.warehouse_id else None
    is_tasting = wh and wh.warehouse_type == 'tasting'
    if not is_tasting and po.status not in (PurchaseStatus.PAID, PurchaseStatus.SHIPPED):
        raise HTTPException(400, f"采购单状态为 '{po.status}'，需要先审批付款才能收货")

    wh_id = po.warehouse_id
    if not wh_id:
        raise HTTPException(400, "采购单没有设置目标仓库")

    from app.models.product import Product
    now = datetime.now(timezone.utc)
    for item in po.items:
        # 换算为瓶数：库存底层按瓶存储
        bpc = 1
        if item.quantity_unit == '箱':
            prod = await db.get(Product, item.product_id)
            bpc = prod.bottles_per_case if prod and prod.bottles_per_case else 1
        bottles = item.quantity * bpc
        # 单瓶成本（unit_price 如果是按"箱"报价，则换算成每瓶）
        per_bottle_cost = Decimal(str(item.unit_price)) / bpc if bpc > 1 else Decimal(str(item.unit_price))

        flow = StockFlow(
            id=str(uuid.uuid4()), flow_no=_gen_no("SF"),
            flow_type="inbound", product_id=item.product_id,
            warehouse_id=wh_id, batch_no=batch_no,
            cost_price=per_bottle_cost, quantity=bottles,
            reference_no=po.po_no, notes=f"采购入库 {po.po_no} ({item.quantity}{item.quantity_unit}={bottles}瓶)",
        )
        db.add(flow)

        inv = (await db.execute(
            select(Inventory).where(
                Inventory.product_id == item.product_id,
                Inventory.warehouse_id == wh_id,
                Inventory.batch_no == batch_no,
            )
        )).scalar_one_or_none()
        if inv:
            inv.quantity += bottles
        else:
            db.add(Inventory(
                product_id=item.product_id, warehouse_id=wh_id,
                batch_no=batch_no, quantity=bottles,
                cost_price=per_bottle_cost, stock_in_date=now,
                source_purchase_order_id=po.id,
            ))

    po.status = PurchaseStatus.RECEIVED
    po.actual_date = now.date()
    await db.flush()
    await log_audit(db, action="receive_purchase_order", entity_type="PurchaseOrder", entity_id=po.id, user=user)
    await db.refresh(po, ["items", "supplier", "warehouse", "brand"])
    return _po_to_response(po)