"""
Brand, Product, Warehouse, Account, and Inventory models.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    AccountType,
    Base,
    InventoryBarcodeStatus,
    InventoryBarcodeType,
    SupplierType,
    WarehouseType,
)

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.user import Employee
    from app.models.order import OrderItem, StockOutAllocation
    from app.models.product import Product


# =============================================================================
# Brand & Product
# =============================================================================

class Brand(Base):
    """Product brand / manufacturer brand line."""

    __tablename__ = "brands"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    manufacturer_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("suppliers.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="active")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    products: Mapped[list["Product"]] = relationship(
        "Product", back_populates="brand", lazy="selectin"
    )


class Product(Base):
    """Product / SKU."""

    __tablename__ = "products"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(20), default="liquor")  # liquor/gift/material/other
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    unit: Mapped[str] = mapped_column(String(20), default="瓶")
    bottles_per_case: Mapped[int] = mapped_column(Integer, default=6)
    purchase_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    sale_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    points_per_case: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    barcode: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )
    spec: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    brand: Mapped[Optional["Brand"]] = relationship(
        "Brand", back_populates="products", lazy="selectin"
    )


# =============================================================================
# Warehouse
# =============================================================================

class Warehouse(Base):
    """Warehouse / storage location."""

    __tablename__ = "warehouses"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    warehouse_type: Mapped[str] = mapped_column(
        String(20),
        default=WarehouseType.MAIN,
        nullable=False,
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    manager_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    brand: Mapped[Optional["Brand"]] = relationship(
        "Brand", foreign_keys=[brand_id], lazy="selectin"
    )

    manager: Mapped[Optional["Employee"]] = relationship("Employee", lazy="selectin")


# =============================================================================
# Account (Financial)
# =============================================================================

class Account(Base):
    """Financial account (cash, f_class, financing). Can be master or project-level."""

    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    level: Mapped[str] = mapped_column(
        String(20), default="project", nullable=False
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    balance: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    bank: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    account_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    brand: Mapped[Optional["Brand"]] = relationship(
        "Brand", foreign_keys=[brand_id], lazy="selectin"
    )


# =============================================================================
# Inventory (Batch-managed)
# =============================================================================

# NOTE: Inventory model moved to inventory.py to avoid circular imports


# =============================================================================
# Supplier / Manufacturer
# =============================================================================

class Supplier(Base):
    """Supplier or manufacturer entity."""

    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(
        String(20),
        default=SupplierType.SUPPLIER,
        nullable=False,
    )
    contact_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tax_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    bank: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    account_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    credit_limit: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    status: Mapped[str] = mapped_column(String(20), default="active")
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    brand: Mapped[Optional["Brand"]] = relationship(
        "Brand", foreign_keys=[brand_id], lazy="selectin"
    )
