"""月度业务员 KPI 快照（决策 #2）

业务背景：
  - 上月老板用"月度排行"决定奖金
  - 下月客户退货会把 completed→refunded，实时聚合查询会悄悄变 GMV
  - 上月业绩数字应当在本月 1 号冻结，写入本表；后台看"实时"查活动表，看"快照"查本表

字段口径：
  - `gmv` = 当月 completed/partial_closed 订单的 received_amount 累加（退货前）
  - `order_count` = 订单数（不含 refunded）
  - `commission_amount` = 当月产生的 Commission 总和（以 order-level 计，不含 adjustment）
  - `snapshot_at` = 冻结时间（月初 1 号 00:05 定时任务跑）

幂等保证：UniqueConstraint(employee_id, period)
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MallMonthlyKpiSnapshot(Base):
    """业务员月度 KPI 快照（冻结型，月底定格不受后续退货影响）。"""

    __tablename__ = "mall_monthly_kpi_snapshot"
    __table_args__ = (
        UniqueConstraint("employee_id", "period",
                         name="uq_mall_kpi_snap_emp_period"),
        Index("ix_mall_kpi_snap_period", "period"),
        Index("ix_mall_kpi_snap_employee", "employee_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # 业务员归属用 ERP employees.id（规则：业务员必绑 linked_employee_id）
    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False,
    )
    # YYYY-MM，例如 2026-04
    period: Mapped[str] = mapped_column(String(7), nullable=False)

    # KPI 数值（都是冻结快照，之后不再变）
    gmv: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0"),
    )
    order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    commission_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0"),
    )

    # 元数据
    snapshot_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(),
        comment="快照生成时间（冻结时刻）",
    )
    notes: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        comment="备注：定时任务 vs 手工回补",
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
