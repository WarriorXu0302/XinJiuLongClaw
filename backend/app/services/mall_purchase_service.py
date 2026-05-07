"""商城 / 门店采购服务层。

核心流程（和 ERP PurchaseOrder 对齐）：
  1. create_po(scope=mall|store, items, 付款计划) → pending
  2. submit_po / approve_po(boss)  → approved（校验账户余额够）
  3. pay_po(finance)               → paid（扣 MALL_MASTER 或 STORE_MASTER 账户）
  4. receive_po(warehouse)         → received / completed（入 mall_inventory 或 ERP store 仓 + 更新加权平均成本）

状态机：pending → approved → paid → received → completed
        │         │         │
        └─ reject / cancel 分支随时可走

关键区别：
  - scope='mall'：items.mall_sku_id 入 mall_warehouses + mall_inventory
    成本：按加权平均更新 mall_inventory.avg_cost_price
  - scope='store'：items.mall_sku_id 入 warehouses(warehouse_type='store') + inventory
    门店仓本质是 ERP 仓，但装的是 mall_products（共享商城 SKU）
    库存跟 ERP inventory 走（需要 inventory 表关联到 mall_product_skus，而不是 products）
    —— 门店场景：门店仓 Inventory.product_id 其实存的是 mall_product_skus.id 对应的 product_id？
       简化：**门店仓也走 mall_inventory**（mall_warehouses.warehouse_type 里加"store"类型？）
       或：门店采购也入 mall_warehouses（门店虚拟仓），不入 ERP warehouses

TODO：为简化，**第一版 scope='store' 的入库也走 mall_inventory，传 mall_warehouse_id 即可**
      UI 在选仓时把 ERP store 仓展现为"门店"，但底层先走 mall 仓表。
      等业务验证后再考虑是否拆两套库存体系。
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mall.inventory import (
    MallInventory,
    MallInventoryFlow,
    MallWarehouse,
)
from app.models.mall.product import MallProductSku
from app.models.mall_purchase import MallPurchaseOrder, MallPurchaseOrderItem
from app.models.product import Account, Supplier


# =============================================================================
# 工具
# =============================================================================


def _gen_po_no() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"MPO-{ts}-{uuid.uuid4().hex[:6]}"


async def _get_expected_account(db: AsyncSession, scope: str) -> Account:
    """按 scope 取对应的专用现金账户。"""
    code = "MALL_MASTER" if scope == "mall" else "STORE_MASTER"
    acc = (await db.execute(
        select(Account).where(Account.code == code)
    )).scalar_one_or_none()
    if acc is None:
        raise HTTPException(
            status_code=500,
            detail=f"账户 {code} 未初始化（migration 应已建好）",
        )
    return acc


# =============================================================================
# 创建
# =============================================================================


async def create_po(
    db: AsyncSession,
    *,
    scope: str,  # mall | store
    supplier_id: str,
    mall_warehouse_id: Optional[str],
    store_warehouse_id: Optional[str],
    items: list[dict],  # [{mall_sku_id, quantity, quantity_unit, unit_price}]
    cash_account_id: Optional[str] = None,
    expected_date: Optional[datetime] = None,
    notes: Optional[str] = None,
    operator_id: Optional[str] = None,
) -> MallPurchaseOrder:
    """建采购单（status=pending）。不扣款、不动库存。"""
    if scope not in ("mall", "store"):
        raise HTTPException(400, "scope 必须是 mall 或 store")

    # 仓校验
    if scope == "mall":
        if not mall_warehouse_id:
            raise HTTPException(400, "商城采购必须指定 mall_warehouse_id")
        wh = await db.get(MallWarehouse, mall_warehouse_id)
        if wh is None or not wh.is_active:
            raise HTTPException(400, "商城仓不存在或已停用")
        store_warehouse_id = None
    else:
        if not store_warehouse_id:
            raise HTTPException(400, "门店采购必须指定 store_warehouse_id")
        from app.models.product import Warehouse
        wh = await db.get(Warehouse, store_warehouse_id)
        if wh is None or wh.warehouse_type != "store" or not wh.is_active:
            raise HTTPException(400, "门店仓不存在或已停用")
        mall_warehouse_id = None

    # 供应商校验
    supplier = await db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(400, "供应商不存在")

    # items 校验
    if not items:
        raise HTTPException(400, "采购单至少一条明细")
    sku_ids = [it["mall_sku_id"] for it in items]
    skus = (await db.execute(
        select(MallProductSku).where(MallProductSku.id.in_(sku_ids))
    )).scalars().all()
    if len(skus) != len(set(sku_ids)):
        missing = set(sku_ids) - {s.id for s in skus}
        raise HTTPException(400, f"以下 SKU 不存在：{list(missing)[:5]}")

    # 账户默认走 MALL_MASTER / STORE_MASTER
    if cash_account_id is None:
        acc = await _get_expected_account(db, scope)
        cash_account_id = acc.id

    # 经营单元归属：scope=mall → mall 事业部，scope=store → 零售事业部
    from app.services.org_unit_service import get_org_unit_id_by_code
    org_unit_id = await get_org_unit_id_by_code(
        db, "mall" if scope == "mall" else "retail"
    )

    po = MallPurchaseOrder(
        id=str(uuid.uuid4()),
        po_no=_gen_po_no(),
        scope=scope,
        org_unit_id=org_unit_id,
        supplier_id=supplier_id,
        mall_warehouse_id=mall_warehouse_id,
        store_warehouse_id=store_warehouse_id,
        cash_account_id=cash_account_id,
        operator_id=operator_id,
        expected_date=expected_date,
        notes=notes,
        status="pending",
    )

    total = Decimal("0")
    for it in items:
        qty = int(it.get("quantity") or 0)
        unit = Decimal(str(it.get("unit_price") or 0))
        if qty <= 0:
            raise HTTPException(400, "数量必须 > 0")
        total += unit * qty
        po.items.append(MallPurchaseOrderItem(
            id=str(uuid.uuid4()),
            po_id=po.id,
            mall_sku_id=it["mall_sku_id"],
            quantity=qty,
            quantity_unit=it.get("quantity_unit") or "瓶",
            unit_price=unit,
        ))

    po.total_amount = total
    po.cash_amount = total
    db.add(po)
    await db.flush()
    return po


# =============================================================================
# 审批
# =============================================================================


async def approve_po(
    db: AsyncSession,
    *,
    po_id: str,
    approver_employee_id: str,
) -> MallPurchaseOrder:
    """boss/admin 批准。**不扣款**，只变状态；留给 pay_po 扣款。"""
    po = (await db.execute(
        select(MallPurchaseOrder)
        .where(MallPurchaseOrder.id == po_id)
        .with_for_update()
    )).scalar_one_or_none()
    if po is None:
        raise HTTPException(404, "采购单不存在")
    if po.status != "pending":
        raise HTTPException(409, f"状态 {po.status} 不可批准")

    po.status = "approved"
    po.approved_by = approver_employee_id
    po.approved_at = datetime.now(timezone.utc)
    await db.flush()
    return po


async def reject_po(
    db: AsyncSession,
    *,
    po_id: str,
    reviewer_employee_id: str,
    reason: str,
) -> MallPurchaseOrder:
    """驳回采购单。"""
    if not reason or not reason.strip():
        raise HTTPException(400, "驳回理由必填")
    po = (await db.execute(
        select(MallPurchaseOrder)
        .where(MallPurchaseOrder.id == po_id)
        .with_for_update()
    )).scalar_one_or_none()
    if po is None:
        raise HTTPException(404, "采购单不存在")
    if po.status != "pending":
        raise HTTPException(409, f"状态 {po.status} 不可驳回")
    po.status = "rejected"
    po.approved_by = reviewer_employee_id
    po.approved_at = datetime.now(timezone.utc)
    po.rejection_reason = reason
    await db.flush()
    return po


# =============================================================================
# 付款（扣账户）
# =============================================================================


async def pay_po(
    db: AsyncSession,
    *,
    po_id: str,
    payer_employee_id: str,
) -> MallPurchaseOrder:
    """finance 付款：扣指定账户余额。"""
    po = (await db.execute(
        select(MallPurchaseOrder)
        .where(MallPurchaseOrder.id == po_id)
        .with_for_update()
    )).scalar_one_or_none()
    if po is None:
        raise HTTPException(404, "采购单不存在")
    if po.status != "approved":
        raise HTTPException(409, f"状态 {po.status} 不可付款")

    # 锁账户扣款
    acc = (await db.execute(
        select(Account)
        .where(Account.id == po.cash_account_id)
        .with_for_update()
    )).scalar_one_or_none()
    if acc is None:
        raise HTTPException(400, "付款账户不存在")
    if acc.balance < po.total_amount:
        raise HTTPException(
            400,
            f"账户 {acc.name} 余额 ¥{acc.balance} 不足支付 ¥{po.total_amount}，"
            f"请先从 master 调拨资金",
        )

    acc.balance -= po.total_amount
    po.status = "paid"
    po.paid_by = payer_employee_id
    po.paid_at = datetime.now(timezone.utc)
    await db.flush()
    return po


# =============================================================================
# 收货 + 入库（更新加权平均成本）
# =============================================================================


async def receive_po(
    db: AsyncSession,
    *,
    po_id: str,
    receiver_employee_id: str,
) -> MallPurchaseOrder:
    """仓管收货：更新 mall_inventory 或 ERP 门店仓 inventory + 加权平均成本。

    简化实现（第一版）：无论 scope 是 mall 还是 store，都走 mall_inventory，
    只是 warehouse_id 不同：
      - scope='mall' → mall_inventory.warehouse_id = po.mall_warehouse_id
      - scope='store' → 门店其实有 MallWarehouse 映射？或者把 ERP 门店仓 id 直接
        当作 mall_inventory.warehouse_id？
    为避免混淆，**第一版限制 scope=store 也走 mall_warehouses（门店仓在 MallWarehouse
    表里建一条）**。路由层把门店选择映射到 mall_warehouses。
    """
    po = (await db.execute(
        select(MallPurchaseOrder)
        .where(MallPurchaseOrder.id == po_id)
        .with_for_update()
    )).scalar_one_or_none()
    if po is None:
        raise HTTPException(404, "采购单不存在")
    if po.status != "paid":
        raise HTTPException(409, f"状态 {po.status} 不可收货（需先付款）")

    # 目前仅支持 scope=mall（store 收货第一版不走此 service，
    # 等业务确认门店仓底层归属再扩展）
    if po.scope != "mall":
        raise HTTPException(
            501,
            "门店采购的收货入库逻辑待业务确认（门店仓底层归属 ERP inventory vs mall_inventory）",
        )

    items = (await db.execute(
        select(MallPurchaseOrderItem).where(MallPurchaseOrderItem.po_id == po.id)
    )).scalars().all()

    now = datetime.now(timezone.utc)
    for it in items:
        # 找到或建 MallInventory
        inv = (await db.execute(
            select(MallInventory)
            .where(MallInventory.warehouse_id == po.mall_warehouse_id)
            .where(MallInventory.sku_id == it.mall_sku_id)
            .with_for_update()
        )).scalar_one_or_none()

        if inv is None:
            inv = MallInventory(
                id=str(uuid.uuid4()),
                warehouse_id=po.mall_warehouse_id,
                sku_id=it.mall_sku_id,
                quantity=it.quantity,
                avg_cost_price=it.unit_price,
            )
            db.add(inv)
        else:
            # 加权平均：new_avg = (old_qty*old_avg + new_qty*new_unit) / (old_qty + new_qty)
            old_qty = inv.quantity or 0
            old_avg = inv.avg_cost_price or Decimal("0")
            new_qty = it.quantity
            new_unit = it.unit_price
            total_qty = old_qty + new_qty
            if total_qty > 0:
                inv.avg_cost_price = (
                    (Decimal(str(old_qty)) * old_avg + Decimal(str(new_qty)) * new_unit)
                    / Decimal(str(total_qty))
                ).quantize(Decimal("0.01"))
            inv.quantity = total_qty

        # 记流水
        db.add(MallInventoryFlow(
            id=str(uuid.uuid4()),
            inventory_id=inv.id,
            flow_type="in",
            quantity=it.quantity,
            cost_price=it.unit_price,
            ref_type="purchase",
            ref_id=po.id,
            notes=f"采购入库 {po.po_no}",
        ))

    po.status = "completed"
    po.received_by = receiver_employee_id
    po.received_at = now
    await db.flush()
    return po


async def cancel_po(
    db: AsyncSession,
    *,
    po_id: str,
    reason: str,
) -> MallPurchaseOrder:
    """取消采购单（仅 pending/approved 允许；paid 的需走退款流程，第一版不支持）。"""
    po = (await db.execute(
        select(MallPurchaseOrder)
        .where(MallPurchaseOrder.id == po_id)
        .with_for_update()
    )).scalar_one_or_none()
    if po is None:
        raise HTTPException(404, "采购单不存在")
    if po.status not in ("pending", "approved"):
        raise HTTPException(
            409,
            f"状态 {po.status} 不可取消（已付款单需走退款流程）",
        )
    po.status = "cancelled"
    po.rejection_reason = reason
    await db.flush()
    return po
