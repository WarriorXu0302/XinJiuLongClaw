"""
Financing order ORM models — bank loan guaranteed by manufacturer.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, FinancingOrderStatus

if TYPE_CHECKING:
    from app.models.product import Account, Brand
    from app.models.user import Employee


class FinancingOrder(Base):
    """Each bank financing event creates one order tracking principal & repayments."""

    __tablename__ = "financing_orders"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    order_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=False
    )
    financing_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    interest_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(8, 4), nullable=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    maturity_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    total_interest: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    repaid_principal: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    repaid_interest: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    outstanding_balance: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default=FinancingOrderStatus.ACTIVE, nullable=False
    )
    bank_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    bank_loan_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    manufacturer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=lambda: datetime.now(timezone.utc)
    )

    brand: Mapped["Brand"] = relationship("Brand", lazy="selectin")
    financing_account: Mapped["Account"] = relationship("Account", lazy="selectin")
    repayments: Mapped[list["FinancingRepayment"]] = relationship(
        "FinancingRepayment",
        back_populates="financing_order",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class FinancingRepayment(Base):
    """Each repayment against a financing order (pending → approved/rejected)."""

    __tablename__ = "financing_repayments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    repayment_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    financing_order_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("financing_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    repayment_type: Mapped[str] = mapped_column(
        String(20), default="normal", nullable=False
    )  # normal | return_warehouse
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )  # pending | approved | rejected
    repayment_date: Mapped[date] = mapped_column(Date, nullable=False)
    interest_days: Mapped[int] = mapped_column(default=0)
    principal_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    interest_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    payment_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=False
    )
    f_class_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    f_class_account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=True
    )
    voucher_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    purchase_order_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reject_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    financing_order: Mapped["FinancingOrder"] = relationship(
        "FinancingOrder", back_populates="repayments"
    )
    payment_account: Mapped["Account"] = relationship(
        "Account", foreign_keys=[payment_account_id], lazy="selectin"
    )
    f_class_account: Mapped[Optional["Account"]] = relationship(
        "Account", foreign_keys=[f_class_account_id], lazy="selectin"
    )
