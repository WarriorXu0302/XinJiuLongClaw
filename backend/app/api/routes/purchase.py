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
    # 跨仓采购：
    #   target_warehouse_type='erp_warehouse' → 传 warehouse_id（指向 warehouses 表）
    #   target_warehouse_type='mall_warehouse' → 传 mall_warehouse_id（指向 mall_warehouses 表）
    # 老接口不传 target_warehouse_type 时默认 erp_warehouse，warehouse_id 必填
    target_warehouse_type: str = "erp_warehouse"  # 'erp_warehouse' | 'mall_warehouse'
    warehouse_id: Optional[str] = None
    mall_warehouse_id: Optional[str] = None
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
    target_warehouse_type: str = "erp_warehouse"
    mall_warehouse_id: Optional[str] = None
    mall_warehouse: Optional[Any] = None  # {id, name}
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
    """Create PO (status=pending). Does NOT deduct money yet。

    跨仓：target_warehouse_type='mall_warehouse' 时要求传 mall_warehouse_id；
    'erp_warehouse' 或不传时要求 warehouse_id（向后兼容）。
    """
    require_role(user, "boss", "purchase", "warehouse")

    # 目标仓校验
    if body.target_warehouse_type == "mall_warehouse":
        if not body.mall_warehouse_id:
            raise HTTPException(400, "入 mall 仓必须指定 mall_warehouse_id")
        from app.models.mall.inventory import MallWarehouse
        mall_wh = await db.get(MallWarehouse, body.mall_warehouse_id)
        if mall_wh is None or not mall_wh.is_active:
            raise HTTPException(400, "mall 仓不存在或已停用")
    else:
        if not body.warehouse_id:
            raise HTTPException(400, "入 ERP 仓必须指定 warehouse_id")

    total = Decimal("0")
    po = PurchaseOrder(
        id=str(uuid.uuid4()),
        po_no=_gen_no("PO"),
        brand_id=body.brand_id,
        supplier_id=body.supplier_id,
        warehouse_id=body.warehouse_id,
        target_warehouse_type=body.target_warehouse_type,
        mall_warehouse_id=body.mall_warehouse_id,
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
    # mall 仓场景不走品鉴豁免（品鉴仓是 ERP 侧语义），必须付款校验
    wh = await db.get(Warehouse, body.warehouse_id) if (
        body.target_warehouse_type == "erp_warehouse" and body.warehouse_id
    ) else None
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
    """Convert PurchaseOrder ORM to response dict with nested names。"""
    d = POResponse.model_validate(po).model_dump()
    d["supplier_name"] = po.supplier.name if po.supplier else None
    d["supplier"] = {"name": po.supplier.name} if po.supplier else None
    d["brand_name"] = po.brand.name if po.brand else None
    d["warehouse"] = (
        {"name": po.warehouse.name, "warehouse_type": po.warehouse.warehouse_type}
        if po.warehouse else None
    )
    # mall 仓信息（跨仓采购时让前端能展示仓名）
    # 不在这里同步查询 MallWarehouse（要 await），前端用 mall_warehouse_id + 列表缓存拼名字，或走详情端点扩展
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


class POReceiveMallBarcodesItem(BaseModel):
    """mall 仓收货时每个 PO 条目的条码列表。"""
    item_id: str
    barcodes: list[str]


class POReceiveBody(BaseModel):
    """收货请求 body。

    ERP 仓路径：barcodes_by_item 可以省略（ERP 自己有条码入库端点 batch-import）。
    mall 仓路径：barcodes_by_item 必填，且每个 PO item 的条码数必须等于应入瓶数。
    """
    batch_no: str
    # mall 仓专用：每个 item_id → 该 item 应收瓶数的条码数组。
    # 厂家防伪码，扫码枪 key-in 或手输；后端做全局唯一 + 本次去重两层校验。
    barcodes_by_item: Optional[list[POReceiveMallBarcodesItem]] = None


@router.post("/{po_id}/receive", response_model=POResponse)
async def receive_purchase_order(
    po_id: str, user: CurrentUser,
    body: POReceiveBody,
    db: AsyncSession = Depends(get_db),
):
    require_role(user, "boss", "warehouse", "purchase")
    po = await db.get(PurchaseOrder, po_id)
    if po is None:
        raise HTTPException(404, "PurchaseOrder not found")
    if po.status in (PurchaseStatus.RECEIVED, PurchaseStatus.COMPLETED):
        raise HTTPException(400, f"采购单已收货，状态: {po.status}")

    is_mall = po.target_warehouse_type == "mall_warehouse"
    batch_no = body.batch_no

    # Normal PO must be paid first; tasting warehouse auto-approved so always ok
    wh = await db.get(Warehouse, po.warehouse_id) if po.warehouse_id else None
    is_tasting = (not is_mall) and wh and wh.warehouse_type == 'tasting'
    if not is_tasting and po.status not in (PurchaseStatus.PAID, PurchaseStatus.SHIPPED):
        raise HTTPException(400, f"采购单状态为 '{po.status}'，需要先审批付款才能收货")

    from app.models.product import Product

    if is_mall:
        # mall 仓入库：必须逐瓶扫描厂家防伪码（白酒业务硬要求）
        # 流程：
        #   (1) 前端传 barcodes_by_item = [{item_id, barcodes: [...]}]
        #   (2) 后端校验每个 item：bars 数量 == 应入瓶数 + 全局唯一 + 本次无重复
        #   (3) 写 MallInventory + 加权平均成本 + MallInventoryBarcode（每瓶一行，status=in_stock）
        #   (4) 任何校验失败整笔回滚
        from app.models.mall.base import (
            MallInventoryBarcodeStatus,
            MallInventoryBarcodeType,
            MallInventoryFlowType,
        )
        from app.models.mall.inventory import (
            MallInventory,
            MallInventoryBarcode,
            MallInventoryFlow,
        )
        from app.models.mall.product import MallProduct, MallProductSku

        if not po.mall_warehouse_id:
            raise HTTPException(400, "PO 标记为 mall 仓但未指定 mall_warehouse_id")

        # 强校验 barcodes 必传
        if body.barcodes_by_item is None:
            raise HTTPException(
                status_code=400,
                detail="mall 仓收货必须提交厂家防伪码列表（barcodes_by_item）",
            )

        # 索引：item_id → barcodes
        barcodes_map: dict[str, list[str]] = {
            b.item_id: [c.strip() for c in b.barcodes if c.strip()]
            for b in body.barcodes_by_item
        }

        # 确保 PO 每个 item 都有条码，不允许漏报
        po_item_ids = {it.id for it in po.items}
        missing_items = po_item_ids - set(barcodes_map)
        if missing_items:
            raise HTTPException(
                status_code=400,
                detail=f"以下 PO item 未提交条码：{list(missing_items)[:3]}（共 {len(missing_items)} 条）",
            )
        extra_items = set(barcodes_map) - po_item_ids
        if extra_items:
            raise HTTPException(
                status_code=400,
                detail=f"提交的 item_id 不属于本 PO：{list(extra_items)[:3]}",
            )

        # 本次所有条码扁平化 + 本次内去重校验
        all_codes_this_batch: list[str] = []
        for codes in barcodes_map.values():
            all_codes_this_batch.extend(codes)
        if len(set(all_codes_this_batch)) != len(all_codes_this_batch):
            # 找出重复的
            seen = set()
            dups = []
            for c in all_codes_this_batch:
                if c in seen:
                    dups.append(c)
                seen.add(c)
            raise HTTPException(
                status_code=400,
                detail=f"本次提交的条码存在重复：{dups[:5]}",
            )

        # 全局唯一：查 mall_inventory_barcodes 是否已存在任一条码
        if all_codes_this_batch:
            existing = (await db.execute(
                select(MallInventoryBarcode.barcode)
                .where(MallInventoryBarcode.barcode.in_(all_codes_this_batch))
            )).scalars().all()
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail=f"以下条码已存在于库存（不可重复入库）：{list(existing)[:5]}",
                )

        now = datetime.now(timezone.utc)
        for item in po.items:
            # 找 mall_product（source_product_id = ERP product.id）
            mall_prod = (await db.execute(
                select(MallProduct).where(MallProduct.source_product_id == item.product_id)
            )).scalar_one_or_none()
            if mall_prod is None:
                raise HTTPException(
                    400,
                    f"ERP 商品 {item.product_id} 还没映射到 mall_products（没有对应的商城商品），"
                    f"无法入 mall 仓。请先在商城商品管理创建对应商品。",
                )
            # mall_sku：默认拿第一个 on_sale 的（单 SKU 场景）；多 SKU 需要界面指定
            sku = (await db.execute(
                select(MallProductSku).where(MallProductSku.product_id == mall_prod.id)
                .order_by(MallProductSku.id)
            )).scalar_one_or_none()
            if sku is None:
                raise HTTPException(
                    400,
                    f"商城商品 {mall_prod.name} 没有 SKU，无法入库",
                )

            bpc = 1
            if item.quantity_unit == '箱':
                prod = await db.get(Product, item.product_id)
                bpc = prod.bottles_per_case if prod and prod.bottles_per_case else 1
            bottles = item.quantity * bpc
            per_bottle_cost = Decimal(str(item.unit_price)) / bpc if bpc > 1 else Decimal(str(item.unit_price))

            # 校验条码数量 == 应入瓶数
            item_barcodes = barcodes_map[item.id]
            if len(item_barcodes) != bottles:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"item {item.id} 应入 {bottles} 瓶（{item.quantity}{item.quantity_unit}×{bpc}），"
                        f"提交条码 {len(item_barcodes)} 个，不匹配"
                    ),
                )

            # 找或建 mall_inventory 行
            inv = (await db.execute(
                select(MallInventory)
                .where(MallInventory.warehouse_id == po.mall_warehouse_id)
                .where(MallInventory.sku_id == sku.id)
                .with_for_update()
            )).scalar_one_or_none()
            if inv is None:
                inv = MallInventory(
                    warehouse_id=po.mall_warehouse_id,
                    sku_id=sku.id,
                    quantity=0,
                    avg_cost_price=per_bottle_cost,
                )
                db.add(inv)
                await db.flush()

            # 加权平均成本：新 avg = (老qty*老avg + 入库qty*本次成本) / (老qty + 入库qty)
            old_qty = inv.quantity or 0
            old_avg = inv.avg_cost_price or Decimal("0")
            new_qty = old_qty + bottles
            if new_qty > 0:
                inv.avg_cost_price = (
                    (Decimal(old_qty) * old_avg + Decimal(bottles) * per_bottle_cost)
                    / Decimal(new_qty)
                ).quantize(Decimal("0.0001"))
            inv.quantity = new_qty

            # 流水
            db.add(MallInventoryFlow(
                inventory_id=inv.id,
                flow_type=MallInventoryFlowType.IN.value,
                quantity=bottles,
                cost_price=per_bottle_cost,
                ref_type="purchase",
                ref_id=po.id,
                notes=f"采购入库 {po.po_no} ({item.quantity}{item.quantity_unit}={bottles}瓶) batch={batch_no}",
            ))

            # 批量写条码（每瓶一行）
            for code in item_barcodes:
                db.add(MallInventoryBarcode(
                    barcode=code,
                    barcode_type=MallInventoryBarcodeType.BOTTLE.value,
                    sku_id=sku.id,
                    product_id=mall_prod.id,
                    warehouse_id=po.mall_warehouse_id,
                    batch_no=batch_no,
                    status=MallInventoryBarcodeStatus.IN_STOCK.value,
                    cost_price=per_bottle_cost,
                ))

        po.status = PurchaseStatus.RECEIVED
        po.actual_date = now.date()
        await db.flush()
        await log_audit(
            db, action="receive_purchase_order", entity_type="PurchaseOrder",
            entity_id=po.id, user=user,
            changes={
                "target": "mall_warehouse",
                "mall_warehouse_id": po.mall_warehouse_id,
                "batch_no": batch_no,
                "barcode_count": len(all_codes_this_batch),
            },
        )
        await db.refresh(po, ["items", "supplier", "warehouse", "brand"])
        return _po_to_response(po)

    # ═══ 原 ERP 仓路径 ═══
    wh_id = po.warehouse_id
    if not wh_id:
        raise HTTPException(400, "采购单没有设置目标仓库")

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