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
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mall.base import MallInventoryFlowType
from app.models.mall.inventory import (
    MallInventory,
    MallInventoryFlow,
    MallWarehouse,
)


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
