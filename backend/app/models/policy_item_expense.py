"""
PolicyItemExpense — expenses incurred during policy item fulfillment.
E.g. flight tickets for 庄园之旅, venue fees for 品鉴会, etc.
Each expense tracks its own reimbursement and profit/loss independently.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.policy_request_item import PolicyRequestItem


class PolicyItemExpense(Base):
    """An expense linked to a policy request item."""

    __tablename__ = "policy_item_expenses"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    request_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("policy_request_items.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)  # 机票、酒店、场地费 etc.
    cost_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )  # 实际支出
    payer_type: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # employee / company
    payer_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True
    )  # 垫付人ID
    reimburse_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )  # 厂家报销金额
    reimburse_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )  # pending / submitted / reimbursed
    profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )  # 盈亏 = reimburse_amount - cost_amount
    voucher_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 凭证
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default="now()")
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=lambda: datetime.now(timezone.utc)
    )

    request_item: Mapped["PolicyRequestItem"] = relationship(
        "PolicyRequestItem", back_populates="expenses"
    )
