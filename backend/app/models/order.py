"""
Order, OrderItem, and StockOutAllocation models.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    CostAllocationMode,
    CustomerSettlementMode,
    OrderPaymentMethod,
    OrderStatus,
    PaymentStatus,
)

if TYPE_CHECKING:
    from app.models.customer import Customer, Receivable
    from app.models.product import Account, Product, Warehouse
    from app.models.user import Employee


class Order(Base):
    """Sales order."""

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    order_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("customers.id"), nullable=True
    )
    salesman_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    # 经营单元归属（brand_agent / retail / mall），报表聚合用
    org_unit_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("org_units.id"), nullable=False, index=True
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default=OrderStatus.PENDING,
        nullable=False,
    )
    payment_status: Mapped[str] = mapped_column(
        String(20),
        default=PaymentStatus.UNPAID,
        nullable=False,
    )
    settlement_mode_snapshot: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    shipped_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    # --- Policy & pricing ---
    deal_unit_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )  # 承诺到手单价（如650）
    deal_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )  # 到手总金额
    policy_template_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("policy_templates.id"), nullable=True
    )
    policy_gap: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )  # 政策差额 = total_amount - deal_amount
    policy_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )  # 政策总价值
    policy_surplus: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )  # 政策红利/折损 = policy_value - policy_gap
    settlement_mode: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # customer_pay / employee_pay / company_pay
    advance_payer_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )  # 垫付人（业务员）
    customer_paid_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )  # 客户实付金额
    policy_receivable: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )  # 政策应收（厂家欠款）
    warehouse_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("warehouses.id"), nullable=True
    )  # 出库仓库

    # --- Delivery & payment ---
    delivery_photos: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    payment_voucher_urls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    customer: Mapped[Optional["Customer"]] = relationship(
        "Customer", lazy="selectin"
    )
    salesman: Mapped[Optional["Employee"]] = relationship(
        "Employee", foreign_keys=[salesman_id], lazy="selectin"
    )
    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", lazy="selectin", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    """Individual line item within a sales order."""

    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("products.id"), nullable=True
    )
    quantity: Mapped[int] = mapped_column(default=0)
    quantity_unit: Mapped[str] = mapped_column(String(10), default="瓶")
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    cost_price_snapshot: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    order: Mapped["Order"] = relationship("Order", back_populates="items")
    product: Mapped[Optional["Product"]] = relationship("Product", lazy="selectin")
    stock_allocations: Mapped[list["StockOutAllocation"]] = relationship(
        "StockOutAllocation",
        back_populates="order_item",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


# =============================================================================
# Stock Flow and Allocations
# =============================================================================

# NOTE: StockFlow and StockOutAllocation models moved to inventory.py
# to consolidate all inventory-related models in one place