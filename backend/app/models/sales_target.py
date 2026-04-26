"""
销售目标模型 — 支持公司/品牌/员工三级目标下达，年/月两种周期。
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.product import Brand
    from app.models.user import Employee


class SalesTarget(Base):
    """销售目标（公司/品牌/员工 三级）"""
    __tablename__ = "sales_targets"
    __table_args__ = (
        UniqueConstraint(
            "target_level", "target_year", "target_month", "brand_id", "employee_id",
            name="uq_sales_target",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    target_level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # company/brand/employee
    target_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    target_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)  # null=年度
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True,
    )
    employee_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True,
    )
    parent_target_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("sales_targets.id"), nullable=True,
    )
    receipt_target: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    sales_target: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    # 达标奖金规则（只在 target_month 非空时生效，即月度目标）
    bonus_at_100: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))  # 完成 100% 奖
    bonus_at_120: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))  # 完成 120% 奖
    bonus_metric: Mapped[str] = mapped_column(String(20), default="receipt")  # receipt / sales 用哪个指标判达标
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 审批流：boss 建目标直接 approved；sales_manager 给下属业务员下目标走 pending_approval
    # status: approved / pending_approval / rejected
    status: Mapped[str] = mapped_column(String(20), default="approved", index=True)
    submitted_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    reject_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=lambda: datetime.now(__import__("datetime").timezone.utc)
    )

    brand: Mapped[Optional["Brand"]] = relationship("Brand", lazy="selectin")
    employee: Mapped[Optional["Employee"]] = relationship("Employee", lazy="selectin")
