"""
Tasting wine models — usage tracking + bottle destruction records.
"""
import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from decimal import Decimal

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.inventory import StockFlow
    from app.models.policy import PolicyUsageRecord
    from app.models.product import Brand, Product, Warehouse
    from app.models.user import Employee


class TastingWineUsage(Base):
    """Tasting wine consumption record.

    usage_type values:
      - entertainment   (招待消耗)
      - customer_use    (客户使用)
      - transfer_backup (转公司备用库)
      - resale          (对外变现)
    """

    __tablename__ = "tasting_wine_usage"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    source_usage_record_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("policy_usage_records.id"), nullable=False
    )
    usage_type: Mapped[str] = mapped_column(String(30), nullable=False)
    product_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("products.id"), nullable=True
    )
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    batch_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    stock_flow_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("stock_flow.id"), nullable=True
    )
    target_warehouse_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("warehouses.id"), nullable=True
    )
    into_company_backup_stock: Mapped[bool] = mapped_column(
        Boolean, default=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    source_usage_record: Mapped["PolicyUsageRecord"] = relationship(
        "PolicyUsageRecord", lazy="selectin"
    )
    product: Mapped[Optional["Product"]] = relationship(
        "Product", lazy="selectin"
    )
    target_warehouse: Mapped[Optional["Warehouse"]] = relationship(
        "Warehouse", lazy="selectin"
    )


class BottleDestruction(Base):
    """Bottle destruction record — tracks empty bottles destroyed by manufacturer staff.

    Business rule: destroyed_count must equal the tasting wine outbound count
    for the same brand + period. Mismatch triggers alert.
    """

    __tablename__ = "bottle_destructions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    record_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=False
    )
    product_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("products.id"), nullable=True
    )
    destroyed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    destruction_date: Mapped[date] = mapped_column(Date, nullable=False)
    period: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    manufacturer_witness: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    witness_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    brand: Mapped["Brand"] = relationship("Brand", lazy="selectin")
    product: Mapped[Optional["Product"]] = relationship("Product", lazy="selectin")
    witness: Mapped[Optional["Employee"]] = relationship(
        "Employee", foreign_keys=[witness_by], lazy="selectin"
    )
