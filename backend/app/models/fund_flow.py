"""
Fund flow model — tracks every balance change with voucher support.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.product import Account
    from app.models.user import Employee


class FundFlow(Base):
    """Every balance change on an account produces one FundFlow record."""

    __tablename__ = "fund_flows"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    flow_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=False
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    flow_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    related_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    related_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    voucher_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    account: Mapped["Account"] = relationship("Account", lazy="selectin")
    approver: Mapped[Optional["Employee"]] = relationship(
        "Employee", foreign_keys=[approved_by], lazy="selectin"
    )