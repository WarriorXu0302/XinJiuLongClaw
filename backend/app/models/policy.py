"""
Policy-related ORM models: policy_requests, policy_usage_records,
policy_claims, policy_claim_items, claim_settlement_links.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    AdvancePayerType,
    ApprovalMode,
    Base,
    ClaimRecordStatus,
    ClaimStatusEnum,
    CostAllocationMode,
    ExecutionStatus,
    ManufacturerExternalStatus,
    OrderStatus,
    PayeeType,
    PaymentRequestStatus,
    PaymentStatus,
    PolicyRequestSource,
    PolicyRequestStatus,
)

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.finance import ManufacturerSettlement
    from app.models.order import Order
    from app.models.policy_request_item import PolicyRequestItem
    from app.models.product import Account, Brand, Supplier
    from app.models.user import Employee


class PolicyRequest(Base):
    """Policy application request — the entry point for all policy-driven benefits.
    Not necessarily tied to an order; supports hospitality, market_activity, and manual sources.
    """

    __tablename__ = "policy_requests"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # --- Source & routing ---
    request_source: Mapped[str] = mapped_column(
        String(30),
        default=PolicyRequestSource.ORDER,
        nullable=False,
    )
    approval_mode: Mapped[str] = mapped_column(
        String(30),
        default=ApprovalMode.INTERNAL_ONLY,
        nullable=False,
    )
    # --- Business references ---
    order_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("orders.id"), nullable=True
    )
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("customers.id"), nullable=True
    )
    target_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    usage_purpose: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    # --- Policy template reference ---
    policy_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("policy_templates.id"), nullable=True
    )
    policy_version_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    policy_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    scheme_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # --- Material items (legacy, for tasting warehouse fulfillment) ---
    material_items: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    # --- Structured policy fields ---
    policy_template_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("policy_templates.id"), nullable=True
    )
    total_policy_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    total_gap: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    settlement_mode: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    # --- Approval ---
    internal_approved_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    manufacturer_approved_by: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default=PolicyRequestStatus.PENDING_INTERNAL,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    order: Mapped[Optional["Order"]] = relationship("Order", lazy="selectin")
    customer: Mapped[Optional["Customer"]] = relationship("Customer", lazy="selectin")
    internal_approver: Mapped[Optional["Employee"]] = relationship(
        "Employee",
        foreign_keys=[internal_approved_by],
        lazy="selectin",
    )
    usage_records: Mapped[list["PolicyUsageRecord"]] = relationship(
        "PolicyUsageRecord",
        back_populates="policy_request",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    request_items: Mapped[list["PolicyRequestItem"]] = relationship(
        "PolicyRequestItem",
        back_populates="policy_request",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="PolicyRequestItem.sort_order",
    )


class PolicyUsageRecord(Base):
    """Policy benefit execution detail — records what actually happened.
    One policy_request can have multiple usage records (e.g., 3 tasting events).
    """

    __tablename__ = "policy_usage_records"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    policy_request_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("policy_requests.id", ondelete="CASCADE"), nullable=False
    )
    benefit_item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    usage_scene: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    usage_applicant_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    planned_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    actual_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    reimbursement_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    # --- Polymorphic advance payer ---
    advance_payer_type: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    advance_employee_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    advance_customer_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("customers.id"), nullable=True
    )
    advance_company_account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=True
    )
    # --- Surplus handling ---
    surplus_handling_type: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True
    )
    # --- Status ---
    execution_status: Mapped[str] = mapped_column(
        String(20),
        default=ExecutionStatus.PENDING,
        nullable=False,
    )
    claim_status: Mapped[str] = mapped_column(
        String(25),
        default=ClaimStatusEnum.UNCLAIMED,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    policy_request: Mapped["PolicyRequest"] = relationship(
        "PolicyRequest", back_populates="usage_records"
    )
    usage_applicant: Mapped[Optional["Employee"]] = relationship(
        "Employee",
        foreign_keys=[usage_applicant_id],
        lazy="selectin",
    )
    advance_employee: Mapped[Optional["Employee"]] = relationship(
        "Employee",
        foreign_keys=[advance_employee_id],
        lazy="selectin",
    )
    advance_customer: Mapped[Optional["Customer"]] = relationship(
        "Customer",
        foreign_keys=[advance_customer_id],
        lazy="selectin",
    )
    advance_company_account: Mapped[Optional["Account"]] = relationship(
        "Account",
        foreign_keys=[advance_company_account_id],
        lazy="selectin",
    )


class PolicyClaim(Base):
    """Policy claim / settlement declaration — financial packing of usage records
    submitted to a manufacturer for reimbursement.
    """

    __tablename__ = "policy_claims"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    claim_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    manufacturer_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("suppliers.id"), nullable=True
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    claim_batch_period: Mapped[str] = mapped_column(String(20), nullable=False)
    claim_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    approved_total_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    settled_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    unsettled_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    status: Mapped[str] = mapped_column(
        String(25),
        default=ClaimRecordStatus.DRAFT,
        nullable=False,
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    claimed_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    manufacturer: Mapped[Optional["Supplier"]] = relationship(
        "Supplier", lazy="selectin"
    )
    brand: Mapped[Optional["Brand"]] = relationship("Brand", lazy="selectin")
    claimant: Mapped[Optional["Employee"]] = relationship(
        "Employee",
        foreign_keys=[claimed_by],
        lazy="selectin",
    )
    items: Mapped[list["PolicyClaimItem"]] = relationship(
        "PolicyClaimItem",
        back_populates="policy_claim",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    settlement_links: Mapped[list["ClaimSettlementLink"]] = relationship(
        "ClaimSettlementLink",
        back_populates="policy_claim",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class PolicyClaimItem(Base):
    """Line item of a policy claim — links to a specific usage record.
    Allows splitting a single usage_record across multiple claim periods.
    """

    __tablename__ = "policy_claim_items"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    claim_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("policy_claims.id", ondelete="CASCADE"), nullable=False
    )
    source_usage_record_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("policy_usage_records.id"), nullable=True
    )
    source_request_item_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("policy_request_items.id"), nullable=True
    )
    declared_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    approved_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    # Snapshot fields: preserve advance payer info at declaration time
    advance_payer_type_snapshot: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    advance_payer_employee_snapshot: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    advance_payer_customer_snapshot: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("customers.id"), nullable=True
    )
    advance_payer_company_snapshot: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default="now()")

    policy_claim: Mapped["PolicyClaim"] = relationship(
        "PolicyClaim", back_populates="items"
    )
    source_usage_record: Mapped["PolicyUsageRecord"] = relationship(
        "PolicyUsageRecord", lazy="selectin"
    )


class ClaimSettlementLink(Base):
    """Many-to-many link between a policy claim and manufacturer settlement records.
    Represents the allocation of a manufacturer payment against a claim.
    """

    __tablename__ = "claim_settlement_links"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    claim_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("policy_claims.id", ondelete="CASCADE"), nullable=False
    )
    settlement_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("manufacturer_settlements.id"), nullable=False
    )
    allocated_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    confirmed_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")

    policy_claim: Mapped["PolicyClaim"] = relationship(
        "PolicyClaim", back_populates="settlement_links"
    )
    settlement: Mapped["ManufacturerSettlement"] = relationship(
        "ManufacturerSettlement",
        back_populates="claim_links",
        lazy="selectin",
    )
    confirmer: Mapped[Optional["Employee"]] = relationship(
        "Employee",
        foreign_keys=[confirmed_by],
        lazy="selectin",
    )
