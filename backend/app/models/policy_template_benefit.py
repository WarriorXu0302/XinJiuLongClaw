"""
PolicyTemplateBenefit — structured benefit items for policy templates.
Replaces the unstructured benefit_rules JSONB with a proper sub-table.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.policy_template import PolicyTemplate
    from app.models.product import Product


class PolicyTemplateBenefit(Base):
    """One benefit item within a policy template.

    Examples:
      - 品鉴会餐费 2场 × ¥1,500 = ¥3,000
      - 品鉴酒 3瓶 × ¥500 = ¥1,500
      - 庄园之旅 1次 × ¥1,000 = ¥1,000
      - 季度返利 30瓶 × ¥30 = ¥900
    """

    __tablename__ = "policy_template_benefits"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("policy_templates.id", ondelete="CASCADE"), nullable=False
    )
    benefit_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # tasting_meal, tasting_wine, travel, rebate, gift, other
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    quantity_unit: Mapped[str] = mapped_column(String(10), default="次")
    standard_unit_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))  # 实际价值单价（厂家面值）
    standard_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))  # 实际价值合计
    unit_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))  # 折算单价（我们到手）
    total_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))  # 折算合计
    product_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("products.id"), nullable=True
    )
    is_material: Mapped[bool] = mapped_column(Boolean, default=False)
    fulfill_mode: Mapped[str] = mapped_column(
        String(20), default="claim"
    )  # claim(需对账到账) / direct(福利直兑) / material(物料出库)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    template: Mapped["PolicyTemplate"] = relationship(
        "PolicyTemplate", back_populates="benefits"
    )
    product: Mapped[Optional["Product"]] = relationship("Product", lazy="selectin")
