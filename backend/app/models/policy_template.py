"""
Policy template and adjustment ORM models.
"""
import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Optional

from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.policy_template_benefit import PolicyTemplateBenefit
    from app.models.product import Brand
    from app.models.user import Employee


class PolicyTemplate(Base):
    """Reusable policy template — defines standard benefit rules and default scheme_no.

    Two template types:
      - channel: matches by case count (min_cases / max_cases)
      - group_purchase: matches by accumulated points → member tier
    """

    __tablename__ = "policy_templates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    template_type: Mapped[str] = mapped_column(
        String(30), default="channel", nullable=False
    )
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    benefit_rules: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    internal_valuation: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # ── Price requirement ──
    required_unit_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )  # 进货价（如885）
    customer_unit_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )  # 客户折算价（如650）
    # ── Channel matching ──
    min_cases: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_cases: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # ── Group purchase matching ──
    member_tier: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    min_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # ── Validity period ──
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # ── Common ──
    default_scheme_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    total_policy_value: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(onupdate=lambda: datetime.now(timezone.utc))

    brand: Mapped[Optional["Brand"]] = relationship("Brand", lazy="selectin")
    benefits: Mapped[list["PolicyTemplateBenefit"]] = relationship(
        "PolicyTemplateBenefit", back_populates="template",
        lazy="selectin", cascade="all, delete-orphan",
        order_by="PolicyTemplateBenefit.sort_order",
    )


class PolicyAdjustment(Base):
    """Adjustment record for a policy request — tracks changes from the template."""

    __tablename__ = "policy_adjustments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    policy_request_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("policy_requests.id", ondelete="CASCADE"), nullable=False
    )
    adjustment_type: Mapped[str] = mapped_column(String(50), nullable=False)
    diff: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    creator: Mapped[Optional["Employee"]] = relationship(
        "Employee", foreign_keys=[created_by], lazy="selectin"
    )
