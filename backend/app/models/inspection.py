"""
Inspection and market cleanup case models.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    InspectionCaseStatus,
    InspectionCaseType,
    MarketCleanupStatus,
)

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.product import Product, Warehouse
    from app.models.user import Employee


class InspectionCase(Base):
    """Market inspection case — tracks violations, redemptions, and rebate deductions."""

    __tablename__ = "inspection_cases"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    case_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    case_type: Mapped[str] = mapped_column(
        String(30),
        default=InspectionCaseType.INSPECTION_VIOLATION,
        nullable=False,
    )
    barcode: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True, index=True
    )
    qrcode: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    batch_no: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )
    product_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("products.id"), nullable=True
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    found_location: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    found_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    found_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    original_order_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("orders.id"), nullable=True
    )
    original_customer_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("customers.id"), nullable=True
    )
    original_sale_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    recovery_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    manufacturer_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    penalty_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    rebate_deduction_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    into_backup_stock: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_stock_cost: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    related_inventory_flow_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("stock_flow.id"), nullable=True
    )
    related_payment_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("payments.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default=InspectionCaseStatus.PENDING,
        nullable=False,
    )
    # New fields for 5-scenario model
    direction: Mapped[str] = mapped_column(String(20), default="outflow")  # outflow / inflow
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    quantity_unit: Mapped[str] = mapped_column(String(10), default="瓶")
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    resell_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    target_warehouse_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("warehouses.id"), nullable=True
    )
    transfer_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    rebate_loss: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    reward_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    deal_unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    profit_loss: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    counterparty: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    no_rebate: Mapped[bool] = mapped_column(Boolean, default=False)
    voucher_urls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    closed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    product: Mapped[Optional["Product"]] = relationship("Product", lazy="selectin")
    finder: Mapped[Optional["Employee"]] = relationship(
        "Employee",
        foreign_keys=[found_by],
        lazy="selectin",
    )
    original_order: Mapped[Optional["Order"]] = relationship("Order", lazy="selectin")


class MarketCleanupCase(Base):
    """Market cleanup case — proactive buyback of competitor market goods."""

    __tablename__ = "market_cleanup_cases"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    case_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    barcode: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True, index=True
    )
    qrcode: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    batch_no: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )
    product_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("products.id"), nullable=True
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    found_location: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    found_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    found_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    buyback_price: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    total_buyback_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    manufacturer_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    into_main_warehouse: Mapped[bool] = mapped_column(Boolean, default=False)
    main_warehouse_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("warehouses.id"), nullable=True
    )
    rebate_increase_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    related_inventory_flow_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("stock_flow.id"), nullable=True
    )
    related_payment_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("payments.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default=MarketCleanupStatus.PENDING,
        nullable=False,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    closed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    product: Mapped[Optional["Product"]] = relationship("Product", lazy="selectin")
    finder: Mapped[Optional["Employee"]] = relationship(
        "Employee",
        foreign_keys=[found_by],
        lazy="selectin",
    )
    main_warehouse: Mapped[Optional["Warehouse"]] = relationship(
        "Warehouse",
        foreign_keys=[main_warehouse_id],
        lazy="selectin",
    )
