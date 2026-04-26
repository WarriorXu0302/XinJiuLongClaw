"""
ExpenseClaim — F类报账 and 日常开销 unified model.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.product import Brand
    from app.models.user import Employee


class ExpenseClaim(Base):
    """Unified expense claim for F-class reimbursement and daily expenses."""

    __tablename__ = "expense_claims"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    claim_no: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    claim_type: Mapped[str] = mapped_column(String(20))  # f_class / daily
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    # F类报账特有
    scheme_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    arrival_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    # 凭证
    voucher_urls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    receipt_urls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)  # 签收单
    # 流程
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending → approved → (f_class: applied→arrived→fulfilled→settled) / (daily: paid→settled)
    applicant_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    approved_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    paid_account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=lambda: datetime.now(timezone.utc)
    )

    brand: Mapped[Optional["Brand"]] = relationship("Brand", lazy="selectin")
    applicant: Mapped[Optional["Employee"]] = relationship(
        "Employee", foreign_keys=[applicant_id], lazy="selectin"
    )
    approver: Mapped[Optional["Employee"]] = relationship(
        "Employee", foreign_keys=[approved_by], lazy="selectin"
    )
