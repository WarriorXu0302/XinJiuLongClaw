"""
Inventory-related ORM models: inventory, inventory_barcodes,
stock_out_allocations, stock_flow.

Note: inventory, stock_out_allocations, and stock_flow were originally
in other modules but are consolidated here for clarity.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    CostAllocationMode,
    InventoryBarcodeStatus,
    InventoryBarcodeType,
)

if TYPE_CHECKING:
    from app.models.order import Order, OrderItem
    from app.models.product import Product, Warehouse
    from app.models.user import Employee


class Inventory(Base):
    """Inventory tracked by (product_id, warehouse_id, batch_no)."""

    __tablename__ = "inventory"

    product_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("products.id"), primary_key=True, index=True
    )
    warehouse_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("warehouses.id"), primary_key=True, index=True
    )
    batch_no: Mapped[str] = mapped_column(
        String(100), primary_key=True, index=True
    )
    quantity: Mapped[int] = mapped_column(default=0)
    cost_price: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    stock_in_date: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    source_purchase_order_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    product: Mapped["Product"] = relationship("Product", lazy="selectin")
    warehouse: Mapped["Warehouse"] = relationship("Warehouse", lazy="selectin")


class InventoryBarcode(Base):
    """Barcode-to-batch mapping for precise inventory tracking.
    Allows scanning a case or bottle barcode to identify its batch and location.
    """

    __tablename__ = "inventory_barcodes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    barcode: Mapped[str] = mapped_column(
        String(200), unique=True, index=True, nullable=False
    )
    barcode_type: Mapped[str] = mapped_column(
        String(20),
        default=InventoryBarcodeType.CASE,
        nullable=False,
    )
    product_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("products.id"), nullable=False
    )
    warehouse_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("warehouses.id"), nullable=False
    )
    batch_no: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    stock_in_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("stock_flow.id"), nullable=True
    )
    parent_barcode: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=InventoryBarcodeStatus.IN_STOCK,
        nullable=False,
    )
    outbound_stock_flow_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("stock_flow.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    product: Mapped["Product"] = relationship("Product", lazy="selectin")
    warehouse: Mapped["Warehouse"] = relationship("Warehouse", lazy="selectin")


class StockOutAllocation(Base):
    """Cost allocation from order item to batch stock flow.
    Tracks which batch (and at what cost) each order item was fulfilled from.
    """

    __tablename__ = "stock_out_allocations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    order_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("order_items.id", ondelete="CASCADE"), nullable=False
    )
    stock_flow_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("stock_flow.id"), nullable=True
    )
    batch_no: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    allocated_quantity: Mapped[int] = mapped_column(default=0)
    allocated_cost_price: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    cost_allocation_mode: Mapped[str] = mapped_column(
        String(30),
        default=CostAllocationMode.FIFO_FALLBACK,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(server_default="now()")

    order_item: Mapped["OrderItem"] = relationship(
        "OrderItem", back_populates="stock_allocations"
    )


class StockFlow(Base):
    """Stock in/out/transfer flow record."""

    __tablename__ = "stock_flow"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    flow_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    product_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("products.id"), nullable=False
    )
    warehouse_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("warehouses.id"), nullable=False
    )
    batch_no: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    flow_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    quantity: Mapped[int] = mapped_column(default=0)
    cost_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    source_order_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("orders.id"), nullable=True
    )
    reference_no: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    operator_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")

    product: Mapped["Product"] = relationship("Product", lazy="selectin")
    warehouse: Mapped["Warehouse"] = relationship("Warehouse", lazy="selectin")
    operator: Mapped[Optional["Employee"]] = relationship("Employee", lazy="selectin")
