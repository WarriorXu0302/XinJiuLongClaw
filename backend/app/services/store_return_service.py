"""门店零售退货 service。

三个动作：
  - apply_return：店员发起（pending）
  - approve_return：admin 批准（approved，实际执行条码/库存/提成冲销）
  - reject_return：admin 驳回（rejected，终态）

业务规则：
  - 只能退 status='completed' 的销售单
  - 一张销售单只能退一次（检查 status='pending' 或 'approved' 的 return 是否存在）
  - 整单退，不支持部分退（简化 v1 设计）
  - 店员只能退本店的单
  - 批准后：条码 OUTBOUND → IN_STOCK，Inventory 回加，StockFlow 记 retail_return
    + Commission status=reversed（不追溯已 settled 的工资）
    + StoreSale.status = 'refunded'（profit 聚合自动排除）
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import InventoryBarcodeStatus
from app.models.inventory import Inventory, InventoryBarcode, StockFlow
from app.models.store_sale import (
    StoreSale,
    StoreSaleItem,
    StoreSaleReturn,
    StoreSaleReturnItem,
)
from app.models.user import Commission, Employee


def _gen_return_no() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"SRR-{ts}-{uuid.uuid4().hex[:6]}"


def _gen_flow_no() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"SF-SR-{ts}-{uuid.uuid4().hex[:5]}"


# =============================================================================
# Apply（店员发起）
# =============================================================================


async def apply_return(
    db: AsyncSession,
    *,
    initiator_employee_id: str,
    original_sale_id: str,
    reason: Optional[str] = None,
) -> StoreSaleReturn:
    """店员申请整单退货。pending 状态，等 admin 批准。"""
    # 校验原单
    sale = await db.get(StoreSale, original_sale_id)
    if sale is None:
        raise HTTPException(status_code=404, detail="原销售单不存在")
    if sale.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"原销售单状态 {sale.status}，不可退货",
        )

    # 只有本店店员能发起（assigned_store_id 必须匹配）
    cashier = await db.get(Employee, initiator_employee_id)
    if cashier is None:
        raise HTTPException(status_code=404, detail="店员不存在")
    if cashier.assigned_store_id != sale.store_id:
        raise HTTPException(
            status_code=403,
            detail="非本店店员，不能发起退货",
        )

    # 一张原单只能有一个活跃退货单
    active = (await db.execute(
        select(StoreSaleReturn)
        .where(StoreSaleReturn.original_sale_id == original_sale_id)
        .where(StoreSaleReturn.status.in_(["pending", "approved"]))
    )).scalar_one_or_none()
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"原单已有活跃退货单（status={active.status}）",
        )

    # 拉原单明细，复制到 return items
    items = (await db.execute(
        select(StoreSaleItem).where(StoreSaleItem.sale_id == original_sale_id)
    )).scalars().all()
    if not items:
        raise HTTPException(status_code=400, detail="原单无明细")

    return_id = str(uuid.uuid4())
    ret = StoreSaleReturn(
        id=return_id,
        return_no=_gen_return_no(),
        original_sale_id=original_sale_id,
        store_id=sale.store_id,
        initiator_employee_id=initiator_employee_id,
        customer_id=sale.customer_id,
        reason=reason,
        status="pending",
        refund_amount=sale.total_sale_amount,
        commission_reversal_amount=sale.total_commission,
        total_bottles=sale.total_bottles,
    )
    db.add(ret)
    await db.flush()

    for it in items:
        db.add(StoreSaleReturnItem(
            id=str(uuid.uuid4()),
            return_id=return_id,
            original_item_id=it.id,
            barcode=it.barcode,
            product_id=it.product_id,
            batch_no_snapshot=it.batch_no_snapshot,
            sale_price_snapshot=it.sale_price,
            commission_reversal=it.commission_amount,
        ))

    await db.flush()
    return ret


# =============================================================================
# Approve（admin/finance 批准，实际执行）
# =============================================================================


async def approve_return(
    db: AsyncSession,
    *,
    return_id: str,
    reviewer_employee_id: str,
) -> StoreSaleReturn:
    """批准退货 → 条码回池 + 库存回加 + Commission reversed + StoreSale refunded。"""
    ret = await db.get(StoreSaleReturn, return_id)
    if ret is None:
        raise HTTPException(status_code=404, detail="退货单不存在")
    if ret.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"退货状态 {ret.status} 不可批准",
        )

    sale = await db.get(StoreSale, ret.original_sale_id)
    if sale is None:
        raise HTTPException(status_code=500, detail="原销售单已丢失")

    return_items = (await db.execute(
        select(StoreSaleReturnItem).where(StoreSaleReturnItem.return_id == return_id)
    )).scalars().all()

    now = datetime.now(timezone.utc)

    # ── 1. 条码 OUTBOUND → IN_STOCK ───────────────────────────
    from collections import defaultdict
    per_batch_qty: dict[tuple[str, str], int] = defaultdict(int)
    per_batch_cost: dict[tuple[str, str], Decimal] = {}

    for ri in return_items:
        bc = (await db.execute(
            select(InventoryBarcode).where(InventoryBarcode.barcode == ri.barcode)
            .with_for_update()
        )).scalar_one_or_none()
        if bc is None:
            raise HTTPException(
                status_code=500,
                detail=f"条码 {ri.barcode} 已消失，无法退",
            )
        if bc.status != InventoryBarcodeStatus.OUTBOUND.value:
            raise HTTPException(
                status_code=400,
                detail=f"条码 {ri.barcode} 当前 status={bc.status}，非 OUTBOUND（可能已流转或重复扫）",
            )
        bc.status = InventoryBarcodeStatus.IN_STOCK.value
        bc.outbound_stock_flow_id = None
        per_batch_qty[(ri.product_id, ri.batch_no_snapshot or "")] += 1

    # ── 2. Inventory 回加（按 product+batch 聚合）───────────
    for (product_id, batch), qty in per_batch_qty.items():
        inv = (await db.execute(
            select(Inventory)
            .where(Inventory.warehouse_id == ret.store_id)
            .where(Inventory.product_id == product_id)
            .where(Inventory.batch_no == batch)
            .with_for_update()
        )).scalar_one_or_none()
        if inv is None:
            raise HTTPException(
                status_code=500,
                detail=f"找不到原 Inventory 行（product={product_id[:8]}, batch={batch}），无法回加",
            )
        inv.quantity += qty
        per_batch_cost[(product_id, batch)] = inv.cost_price

    # ── 3. StockFlow：按 batch 聚合一条 retail_return 回单 ──
    for (product_id, batch), qty in per_batch_qty.items():
        cost = per_batch_cost.get((product_id, batch), Decimal("0"))
        db.add(StockFlow(
            id=str(uuid.uuid4()),
            flow_no=_gen_flow_no(),
            flow_type="retail_return",
            product_id=product_id,
            warehouse_id=ret.store_id,
            batch_no=batch,
            quantity=qty,
            cost_price=cost,
            reference_no=ret.return_no,
            notes=f"门店退货入库 {ret.return_no}（原单 {sale.sale_no}）",
        ))

    # ── 4. Commission 冲销（原单 commission.status=pending → reversed；settled 不动）──
    commissions = (await db.execute(
        select(Commission).where(Commission.store_sale_id == sale.id)
    )).scalars().all()
    reversed_count = 0
    kept_settled_count = 0
    for c in commissions:
        if c.status == "pending":
            c.status = "reversed"
            c.notes = ((c.notes or "") + f"\n[退货冲销] return_no={ret.return_no}").strip()
            reversed_count += 1
        elif c.status == "settled":
            kept_settled_count += 1
            # 已结算（工资已发）不动，审计 notes 提示一下；业务侧走下月工资扣回
            c.notes = ((c.notes or "") + f"\n[退货但已 settled] return_no={ret.return_no}").strip()

    # ── 5. 原销售单 status → refunded（profit_service 自动排除）──
    sale.status = "refunded"

    # ── 6. 退货单状态 ─────────────────────────
    ret.status = "refunded"
    ret.reviewer_employee_id = reviewer_employee_id
    ret.reviewed_at = now

    await db.flush()
    return ret


# =============================================================================
# Reject（admin/finance 驳回）
# =============================================================================


async def reject_return(
    db: AsyncSession,
    *,
    return_id: str,
    reviewer_employee_id: str,
    rejection_reason: str,
) -> StoreSaleReturn:
    """驳回退货 → 不动任何数据，只标 rejected + 理由。"""
    ret = await db.get(StoreSaleReturn, return_id)
    if ret is None:
        raise HTTPException(status_code=404, detail="退货单不存在")
    if ret.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"退货状态 {ret.status} 不可驳回",
        )
    if not rejection_reason or not rejection_reason.strip():
        raise HTTPException(status_code=400, detail="驳回理由必填")

    ret.status = "rejected"
    ret.rejection_reason = rejection_reason
    ret.reviewer_employee_id = reviewer_employee_id
    ret.reviewed_at = datetime.now(timezone.utc)
    await db.flush()
    return ret
