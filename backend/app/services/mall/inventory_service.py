"""
Mall 库存服务。

职责（M3 范围）：
  - deduct_for_order：下单时原子扣库存 + 记 flow（out）
  - restock_for_cancel：取消订单时退回库存 + 记 flow（in）
  - apply_inbound / apply_outbound：M2 采购/管理后台调拨时用（M5 再连采购路由）

关键点：
  - deduct_for_order 必须 SELECT FOR UPDATE 锁定库存行，防并发扣负
  - DB 还有 CHECK(quantity >= 0) 兜底，即使逻辑漏校验也不会出现负库存
  - 退货/取消不动 avg_cost_price，只用原单成本记录流水
"""
import uuid
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mall.base import (
    MallInventoryBarcodeStatus,
    MallInventoryBarcodeType,
    MallInventoryFlowType,
)
from app.models.mall.inventory import (
    MallInventory,
    MallInventoryBarcode,
    MallInventoryFlow,
    MallWarehouse,
)
from app.models.mall.product import MallProductSku


async def get_default_warehouse(db: AsyncSession) -> Optional[MallWarehouse]:
    """取第一个 active 的仓（M3 简化：所有订单从这一个仓扣）。

    M5 管理后台可配置每业务员默认仓；此处兜底取最早的 active 仓。
    """
    return (
        await db.execute(
            select(MallWarehouse)
            .where(MallWarehouse.is_active.is_(True))
            .order_by(MallWarehouse.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()


async def deduct_for_order(
    db: AsyncSession,
    *,
    warehouse_id: str,
    sku_id: int,
    quantity: int,
    order_id: str,
) -> Decimal | None:
    """从指定仓扣减 SKU 库存；返回当时 avg_cost_price 用于订单 cost 快照。

    并发安全：
      - SELECT ... FOR UPDATE 锁 MallInventory 行
      - 校验 quantity 足够
      - UPDATE quantity -= quantity；若因其他原因降到负数，DB CHECK 兜底抛异常
    """
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="数量必须大于 0")

    row = (
        await db.execute(
            select(MallInventory)
            .where(MallInventory.warehouse_id == warehouse_id)
            .where(MallInventory.sku_id == sku_id)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if row is None or row.quantity < quantity:
        available = row.quantity if row else 0
        raise HTTPException(
            status_code=400,
            detail=f"库存不足（SKU {sku_id}：需 {quantity}，剩 {available}）",
        )

    row.quantity -= quantity
    # 流水记录（quantity 记负值表示出库）
    flow = MallInventoryFlow(
        inventory_id=row.id,
        flow_type=MallInventoryFlowType.OUT.value,
        quantity=-quantity,
        cost_price=row.avg_cost_price,
        ref_type="order",
        ref_id=order_id,
    )
    db.add(flow)
    await db.flush()
    return row.avg_cost_price


async def restock_for_cancel(
    db: AsyncSession,
    *,
    warehouse_id: str,
    sku_id: int,
    quantity: int,
    order_id: str,
    cost_price: Decimal | None = None,
) -> None:
    """取消订单时退回库存。用原单 cost_price 记流水，不动 avg_cost_price。"""
    if quantity <= 0:
        return

    row = (
        await db.execute(
            select(MallInventory)
            .where(MallInventory.warehouse_id == warehouse_id)
            .where(MallInventory.sku_id == sku_id)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if row is None:
        # 极端：下单时存在的仓被删了。M3 不处理，抛错好过静默
        raise HTTPException(
            status_code=500,
            detail=f"退回库存失败：仓 {warehouse_id} / SKU {sku_id} 记录不存在",
        )

    row.quantity += quantity
    flow = MallInventoryFlow(
        inventory_id=row.id,
        flow_type=MallInventoryFlowType.IN.value,
        quantity=quantity,
        cost_price=cost_price,
        ref_type="order_cancel",
        ref_id=order_id,
    )
    db.add(flow)
    await db.flush()


async def apply_inbound(
    db: AsyncSession,
    *,
    warehouse_id: str,
    sku_id: int,
    quantity: int,
    unit_cost: Decimal,
    ref_type: str,
    ref_id: str | None = None,
) -> MallInventory:
    """入库 + 更新加权平均成本。M5 采购收货 / 调拨时调用。"""
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="入库数量必须大于 0")

    row = (
        await db.execute(
            select(MallInventory)
            .where(MallInventory.warehouse_id == warehouse_id)
            .where(MallInventory.sku_id == sku_id)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if row is None:
        row = MallInventory(
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            quantity=quantity,
            avg_cost_price=unit_cost,
        )
        db.add(row)
        await db.flush()
    else:
        # 加权平均：(old_qty * old_avg + new_qty * new_cost) / (old_qty + new_qty)
        old_qty = row.quantity
        old_avg = row.avg_cost_price or Decimal("0")
        new_total_qty = old_qty + quantity
        if new_total_qty > 0:
            row.avg_cost_price = (
                (old_qty * old_avg + quantity * unit_cost) / new_total_qty
            ).quantize(Decimal("0.01"))
        row.quantity = new_total_qty

    flow = MallInventoryFlow(
        inventory_id=row.id,
        flow_type=MallInventoryFlowType.IN.value,
        quantity=quantity,
        cost_price=unit_cost,
        ref_type=ref_type,
        ref_id=ref_id,
    )
    db.add(flow)
    await db.flush()
    return row


# =============================================================================
# 条码入库（A 方案出库扫码的前置流程）
# =============================================================================

async def inbound_with_barcodes(
    db: AsyncSession,
    *,
    warehouse_id: str,
    sku_id: int,
    quantity: int,
    unit_cost: Decimal,
    batch_no: str,
    ref_type: str = "inbound",
    ref_id: Optional[str] = None,
    barcode_prefix: Optional[str] = None,
    custom_barcodes: Optional[list[str]] = None,
) -> tuple[MallInventory, list[MallInventoryBarcode]]:
    """入库 + 按数量生成单瓶条码。

    参数：
      quantity       入库瓶数（> 0）
      unit_cost      单瓶成本
      batch_no       生产批次号（厂家标注，用于追溯）
      barcode_prefix 条码前缀。None 则自动生成 `MBC-{sku}-{6 位 uuid}` 序列
      custom_barcodes 若提供：直接用这批条码（来自厂家贴码 / CSV 导入），
                     长度必须 == quantity，且全局 unique

    返回：(MallInventory, 新建的 barcode 列表)

    幂等：custom_barcodes 若有任一已存在 → 抛错回滚；不允许"入了一半"。
    """
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="入库数量必须大于 0")
    if not batch_no or not batch_no.strip():
        raise HTTPException(status_code=400, detail="生产批次号 batch_no 必填")

    # 校验 SKU 存在
    sku = (await db.execute(
        select(MallProductSku).where(MallProductSku.id == sku_id)
    )).scalar_one_or_none()
    if sku is None:
        raise HTTPException(status_code=404, detail=f"SKU {sku_id} 不存在")

    # ── 处理条码来源 ──────────────────────────────────────
    if custom_barcodes is not None:
        if len(custom_barcodes) != quantity:
            raise HTTPException(
                status_code=400,
                detail=f"上传条码数 {len(custom_barcodes)} ≠ 入库数量 {quantity}",
            )
        # 条码内部去重
        if len(set(custom_barcodes)) != len(custom_barcodes):
            raise HTTPException(status_code=400, detail="上传条码包含重复")
        # 条码全局唯一校验
        existing = (await db.execute(
            select(MallInventoryBarcode.barcode)
            .where(MallInventoryBarcode.barcode.in_(custom_barcodes))
        )).scalars().all()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"条码已存在：{', '.join(existing[:5])}",
            )
        codes = list(custom_barcodes)
    else:
        # 自动生成：MBC-{sku_id:03d}-{8 位 uuid}
        prefix = barcode_prefix or f"MBC-{sku_id:03d}"
        codes = [f"{prefix}-{uuid.uuid4().hex[:8].upper()}" for _ in range(quantity)]

    # ── 扣数量 + 加权平均成本 ─────────────────────────────
    inv = await apply_inbound(
        db,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        quantity=quantity,
        unit_cost=unit_cost,
        ref_type=ref_type,
        ref_id=ref_id,
    )

    # ── 批量写 barcode ────────────────────────────────────
    rows: list[MallInventoryBarcode] = []
    for code in codes:
        b = MallInventoryBarcode(
            barcode=code,
            barcode_type=MallInventoryBarcodeType.BOTTLE.value,
            sku_id=sku_id,
            product_id=sku.product_id,
            warehouse_id=warehouse_id,
            batch_no=batch_no.strip(),
            status=MallInventoryBarcodeStatus.IN_STOCK.value,
            cost_price=unit_cost,
        )
        db.add(b)
        rows.append(b)

    await db.flush()
    return inv, rows


async def adjust_barcode_damaged(
    db: AsyncSession,
    *,
    barcode: str,
    reason: Optional[str] = None,
) -> MallInventoryBarcode:
    """单瓶盘亏 / 损耗：条码 in_stock → damaged，库存 -1，不改 avg_cost。"""
    b = (await db.execute(
        select(MallInventoryBarcode)
        .where(MallInventoryBarcode.barcode == barcode)
        .with_for_update()
    )).scalar_one_or_none()
    if b is None:
        raise HTTPException(status_code=404, detail=f"条码 {barcode} 不存在")
    if b.status != MallInventoryBarcodeStatus.IN_STOCK.value:
        raise HTTPException(
            status_code=400,
            detail=f"条码状态 {b.status}，无法标记损耗",
        )

    inv = (await db.execute(
        select(MallInventory)
        .where(MallInventory.warehouse_id == b.warehouse_id)
        .where(MallInventory.sku_id == b.sku_id)
        .with_for_update()
    )).scalar_one_or_none()
    if inv is not None:
        inv.quantity = max(inv.quantity - 1, 0)

    flow = MallInventoryFlow(
        inventory_id=inv.id if inv else None,
        flow_type=MallInventoryFlowType.LOSS.value,
        quantity=-1,
        cost_price=b.cost_price,
        ref_type="barcode_damage",
        ref_id=b.id,
        notes=reason,
    )
    db.add(flow)
    b.status = MallInventoryBarcodeStatus.DAMAGED.value
    await db.flush()
    return b
