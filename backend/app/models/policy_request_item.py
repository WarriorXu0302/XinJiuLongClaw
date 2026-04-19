"""
PolicyRequestItem — structured benefit items for a policy request.
Each item tracks its own fulfillment lifecycle independently.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.inventory import StockFlow
    from app.models.policy import PolicyRequest
    from app.models.policy_item_expense import PolicyItemExpense
    from app.models.product import Product
    from app.models.product import Product


class PolicyRequestItem(Base):
    """One benefit item within a policy request, with independent fulfillment tracking.

    Lifecycle: pending → applied → fulfilled → settled
    """

    __tablename__ = "policy_request_items"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    policy_request_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("policy_requests.id", ondelete="CASCADE"), nullable=False
    )
    benefit_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    quantity_unit: Mapped[str] = mapped_column(String(10), default="次")
    standard_unit_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))  # 实际价值单价
    standard_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))  # 实际价值合计
    unit_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))  # 折算单价
    total_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))  # 折算合计
    product_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("products.id"), nullable=True
    )
    is_material: Mapped[bool] = mapped_column(Boolean, default=False)
    fulfill_mode: Mapped[str] = mapped_column(
        String(20), default="claim"
    )  # claim(需对账到账) / direct(福利直兑) / material(物料出库)

    # Who pays upfront
    advance_payer_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    advance_payer_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    # Fulfillment tracking
    fulfill_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )  # pending → applied → arrived → fulfilled → settled
    fulfilled_qty: Mapped[int] = mapped_column(Integer, default=0)  # 已兑付数量（逐次累加）
    applied_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    fulfilled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    settled_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    stock_flow_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("stock_flow.id"), nullable=True
    )
    actual_cost: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))  # 实际花费
    profit_loss: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))  # 盈亏 = 面值 - 折算(承诺客户) - 实际花费
    # Arrival tracking (厂家到账)
    arrival_billcode: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    arrival_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    arrival_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    # Fulfillment voucher (兑付凭证)
    voucher_urls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    confirmed_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    scheme_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=lambda: datetime.now(timezone.utc)
    )

    policy_request: Mapped["PolicyRequest"] = relationship(
        "PolicyRequest", back_populates="request_items"
    )
    product: Mapped[Optional["Product"]] = relationship("Product", lazy="selectin")
    expenses: Mapped[list["PolicyItemExpense"]] = relationship(
        "PolicyItemExpense", back_populates="request_item",
        lazy="selectin", cascade="all, delete-orphan",
    )
