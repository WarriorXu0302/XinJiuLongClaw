"""
Customer and Receivable models.
"""
import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CustomerSettlementMode

if TYPE_CHECKING:
    from app.models.user import Employee, User


class Customer(Base):
    """Customer / client entity."""

    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_type: Mapped[str] = mapped_column(
        String(20), default="channel", nullable=False
    )
    contact_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    contact_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    settlement_mode: Mapped[str] = mapped_column(
        String(20),
        default=CustomerSettlementMode.CASH,
        nullable=False,
    )
    credit_days: Mapped[int] = mapped_column(Numeric(5, 0), default=0)
    credit_limit: Mapped[float] = mapped_column(Numeric(15, 2), default=0.0)
    salesman_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="active")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    salesman: Mapped[Optional["Employee"]] = relationship(
        "Employee", lazy="selectin"
    )
    receivables: Mapped[list["Receivable"]] = relationship(
        "Receivable", back_populates="customer", lazy="selectin"
    )


class CustomerBrandSalesman(Base):
    """Three-way binding: customer × brand × salesman.
    One customer has one salesman per brand.
    """

    __tablename__ = "customer_brand_salesman"
    __table_args__ = (
        UniqueConstraint("customer_id", "brand_id", name="uq_customer_brand"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    customer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    salesman_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Receivable(Base):
    """Accounts receivable record.
    Auto-generated when an order for a credit customer is delivered.
    """

    __tablename__ = "receivables"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    receivable_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    customer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("customers.id"), nullable=False
    )
    order_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("orders.id"), nullable=True
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    paid_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0.0)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="unpaid"
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    customer: Mapped["Customer"] = relationship(
        "Customer", back_populates="receivables", lazy="selectin"
    )
