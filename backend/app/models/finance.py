"""
Finance-related ORM models: receipts, payments, expenses,
payment_requests, manufacturer_settlements.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    AccountType,
    AdvancePayerType,
    Base,
    ClaimStatusEnum,
    CostAllocationMode,
    EmployeeStatus,
    ExpenseStatus,
    ManufacturerExternalStatus,
    OrderPaymentMethod,
    OrderStatus,
    PayeeType,
    PaymentRequestStatus,
    PaymentStatus,
    PaymentType,
)

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.order import Order
    from app.models.policy import ClaimSettlementLink, PolicyClaim, PolicyUsageRecord
    from app.models.product import Account, Brand, Supplier
    from app.models.user import Employee


class Receipt(Base):
    """Cash receipt record — money received from a customer."""

    __tablename__ = "receipts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    receipt_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("customers.id"), nullable=True
    )
    order_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("orders.id"), nullable=True
    )
    account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=True
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(
        String(20),
        default=OrderPaymentMethod.BANK,
        nullable=False,
    )
    receipt_date: Mapped[date] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    customer: Mapped[Optional["Customer"]] = relationship("Customer", lazy="selectin")
    order: Mapped[Optional["Order"]] = relationship("Order", lazy="selectin")
    account: Mapped[Optional["Account"]] = relationship("Account", lazy="selectin")


class Payment(Base):
    """Payment record — money paid out (to supplier, expense, refund, etc.)."""

    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    payment_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    payee: Mapped[str] = mapped_column(String(200), nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=True
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    payment_type: Mapped[str] = mapped_column(
        String(20),
        default=PaymentType.EXPENSE,
        nullable=False,
    )
    payment_method: Mapped[str] = mapped_column(
        String(20),
        default=OrderPaymentMethod.BANK,
        nullable=False,
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    account: Mapped[Optional["Account"]] = relationship("Account", lazy="selectin")


class Expense(Base):
    """Employee expense reimbursement record."""

    __tablename__ = "expenses"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    expense_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    category_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("expense_categories.id"), nullable=True
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    payment_account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=True
    )
    reimbursement_account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=True
    )
    reimbursement_ratio: Mapped[Decimal] = mapped_column(
        Numeric(6, 3), default=Decimal("1.000")
    )
    actual_cost: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    voucher_urls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    applicant_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    approved_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default=ExpenseStatus.PENDING,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    payment_account: Mapped[Optional["Account"]] = relationship(
        "Account",
        foreign_keys=[payment_account_id],
        lazy="selectin",
    )
    reimbursement_account: Mapped[Optional["Account"]] = relationship(
        "Account",
        foreign_keys=[reimbursement_account_id],
        lazy="selectin",
    )
    applicant: Mapped[Optional["Employee"]] = relationship(
        "Employee",
        foreign_keys=[applicant_id],
        lazy="selectin",
    )
    approver: Mapped[Optional["Employee"]] = relationship(
        "Employee",
        foreign_keys=[approved_by],
        lazy="selectin",
    )


class ExpenseCategory(Base):
    """Expense category for classification."""

    __tablename__ = "expense_categories"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")


class ManufacturerSettlement(Base):
    """Manufacturer actual payment record.
    Tracks when a manufacturer transfers money to the company.
    One settlement can settle multiple claims via claim_settlement_links.
    """

    __tablename__ = "manufacturer_settlements"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    settlement_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    manufacturer_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("suppliers.id"), nullable=True
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    settlement_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    approved_claim_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    settled_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    unsettled_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    settlement_date: Mapped[date] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )
    confirmed_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    manufacturer: Mapped[Optional["Supplier"]] = relationship(
        "Supplier", lazy="selectin"
    )
    brand: Mapped[Optional["Brand"]] = relationship("Brand", lazy="selectin")
    confirmer: Mapped[Optional["Employee"]] = relationship(
        "Employee",
        foreign_keys=[confirmed_by],
        lazy="selectin",
    )
    claim_links: Mapped[list["ClaimSettlementLink"]] = relationship(
        "ClaimSettlementLink",
        back_populates="settlement",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class FinancePaymentRequest(Base):
    """Payment request for internal advance repayment.
    Generated when a manufacturer settlement is confirmed and the advance
    was made by an employee or customer.
    NOTE: Named FinancePaymentRequest to avoid collision with the policy module's
    payment_requests concept. The actual table name is `payment_requests`.
    """

    __tablename__ = "payment_requests"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    request_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    source_usage_record_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("policy_usage_records.id"), nullable=True
    )
    related_claim_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("policy_claims.id"), nullable=True
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    # --- Polymorphic payee ---
    payee_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    payee_employee_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    payee_customer_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("customers.id"), nullable=True
    )
    payee_other_name: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default=PaymentRequestStatus.PENDING,
        nullable=False,
    )
    payable_account_type: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    payable_account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=True
    )
    approved_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    source_usage_record: Mapped[Optional["PolicyUsageRecord"]] = relationship(
        "PolicyUsageRecord", lazy="selectin"
    )
    related_claim: Mapped[Optional["PolicyClaim"]] = relationship(
        "PolicyClaim", lazy="selectin"
    )
    payee_employee: Mapped[Optional["Employee"]] = relationship(
        "Employee",
        foreign_keys=[payee_employee_id],
        lazy="selectin",
    )
    payee_customer: Mapped[Optional["Customer"]] = relationship(
        "Customer",
        foreign_keys=[payee_customer_id],
        lazy="selectin",
    )
    payable_account: Mapped[Optional["Account"]] = relationship(
        "Account",
        foreign_keys=[payable_account_id],
        lazy="selectin",
    )
    approver: Mapped[Optional["Employee"]] = relationship(
        "Employee",
        foreign_keys=[approved_by],
        lazy="selectin",
    )
