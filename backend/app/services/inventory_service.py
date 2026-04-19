"""
Inventory service — stock-out processing with barcode-exact
and FIFO-fallback batch deduction.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import CostAllocationMode, InventoryBarcodeStatus
from app.models.inventory import (
    Inventory,
    InventoryBarcode,
    StockFlow,
    StockOutAllocation,
)
from app.models.order import OrderItem


def _generate_flow_no() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:8]
    return f"SF-{ts}-{short}"


async def process_stock_out(
    db: AsyncSession,
    *,
    order_item_id: str,
    product_id: str,
    required_quantity: int,
    warehouse_id: str,
    barcode: str | None = None,
) -> list[StockOutAllocation]:
    """Execute stock-out for a single order item.

    Strategy:
      1. If *barcode* is provided AND maps to an in-stock batch,
         deduct from that exact batch  (cost_allocation_mode = barcode_exact).
      2. Otherwise fall back to FIFO across all batches in the warehouse
         (cost_allocation_mode = fifo_fallback).

    Returns the created StockOutAllocation rows.
    Raises ValueError on insufficient inventory.
    """
    if required_quantity <= 0:
        raise ValueError("required_quantity must be > 0")

    # Resolve source order_id for stock_flow
    item = await db.get(OrderItem, order_item_id)
    if item is None:
        raise ValueError(f"OrderItem {order_item_id} not found")
    source_order_id = item.order_id

    # ------------------------------------------------------------------
    # 1. Try barcode-exact deduction
    # ------------------------------------------------------------------
    if barcode:
        bc_row = (
            await db.execute(
                select(InventoryBarcode)
                .where(
                    InventoryBarcode.barcode == barcode,
                    InventoryBarcode.product_id == product_id,
                    InventoryBarcode.warehouse_id == warehouse_id,
                    InventoryBarcode.status == InventoryBarcodeStatus.IN_STOCK,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

        if bc_row is not None:
            return await _deduct_exact(
                db,
                bc_row=bc_row,
                order_item_id=order_item_id,
                product_id=product_id,
                warehouse_id=warehouse_id,
                required_quantity=required_quantity,
                source_order_id=source_order_id,
            )

    # ------------------------------------------------------------------
    # 2. FIFO fallback
    # ------------------------------------------------------------------
    return await _deduct_fifo(
        db,
        order_item_id=order_item_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        required_quantity=required_quantity,
        source_order_id=source_order_id,
    )


# =====================================================================
# Internal helpers
# =====================================================================


async def _deduct_exact(
    db: AsyncSession,
    *,
    bc_row: InventoryBarcode,
    order_item_id: str,
    product_id: str,
    warehouse_id: str,
    required_quantity: int,
    source_order_id: str,
) -> list[StockOutAllocation]:
    """Deduct from the batch identified by a scanned barcode."""
    batch_no = bc_row.batch_no

    inv = (
        await db.execute(
            select(Inventory)
            .where(
                Inventory.product_id == product_id,
                Inventory.warehouse_id == warehouse_id,
                Inventory.batch_no == batch_no,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if inv is None or inv.quantity < required_quantity:
        available = inv.quantity if inv else 0
        raise ValueError(
            f"Insufficient stock in batch {batch_no}: "
            f"need {required_quantity}, available {available}"
        )

    # Deduct inventory
    inv.quantity -= required_quantity

    # Create stock_flow
    flow = StockFlow(
        id=str(uuid.uuid4()),
        flow_no=_generate_flow_no(),
        product_id=product_id,
        warehouse_id=warehouse_id,
        batch_no=batch_no,
        flow_type="out",
        quantity=-required_quantity,
        cost_price=inv.cost_price,
        source_order_id=source_order_id,
    )
    db.add(flow)

    # Create allocation
    alloc = StockOutAllocation(
        id=str(uuid.uuid4()),
        order_item_id=order_item_id,
        stock_flow_id=flow.id,
        batch_no=batch_no,
        allocated_quantity=required_quantity,
        allocated_cost_price=inv.cost_price,
        cost_allocation_mode=CostAllocationMode.BARCODE_EXACT,
    )
    db.add(alloc)

    # Mark barcode as outbound
    bc_row.status = InventoryBarcodeStatus.OUTBOUND
    bc_row.outbound_stock_flow_id = flow.id

    await db.flush()
    return [alloc]


async def _deduct_fifo(
    db: AsyncSession,
    *,
    order_item_id: str,
    product_id: str,
    warehouse_id: str,
    required_quantity: int,
    source_order_id: str,
) -> list[StockOutAllocation]:
    """Deduct across batches in FIFO order (oldest stock_in_date first)."""
    rows = (
        await db.execute(
            select(Inventory)
            .where(
                Inventory.product_id == product_id,
                Inventory.warehouse_id == warehouse_id,
                Inventory.quantity > 0,
            )
            .order_by(Inventory.stock_in_date.asc(), Inventory.created_at.asc())
            .with_for_update()
        )
    ).scalars().all()

    total_available = sum(r.quantity for r in rows)
    if total_available < required_quantity:
        raise ValueError(
            f"Insufficient FIFO stock for product {product_id} "
            f"in warehouse {warehouse_id}: "
            f"need {required_quantity}, available {total_available}"
        )

    remaining = required_quantity
    allocations: list[StockOutAllocation] = []

    for inv in rows:
        if remaining <= 0:
            break

        take = min(inv.quantity, remaining)
        inv.quantity -= take
        remaining -= take

        flow = StockFlow(
            id=str(uuid.uuid4()),
            flow_no=_generate_flow_no(),
            product_id=product_id,
            warehouse_id=warehouse_id,
            batch_no=inv.batch_no,
            flow_type="out",
            quantity=-take,
            cost_price=inv.cost_price,
            source_order_id=source_order_id,
        )
        db.add(flow)

        alloc = StockOutAllocation(
            id=str(uuid.uuid4()),
            order_item_id=order_item_id,
            stock_flow_id=flow.id,
            batch_no=inv.batch_no,
            allocated_quantity=take,
            allocated_cost_price=inv.cost_price,
            cost_allocation_mode=CostAllocationMode.FIFO_FALLBACK,
        )
        db.add(alloc)
        allocations.append(alloc)

    await db.flush()
    return allocations
