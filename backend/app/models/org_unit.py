"""OrgUnit（经营单元）— 给老板看"分公司视角"用的分析维度。

设计定位：
  - 这不是法务分公司，也不是组织架构主轴。
  - brand 依然是 RLS/账务的主轴，org_unit 只是附在 orders/commissions/store_sales/
    mall_orders/mall_purchase_orders 上的一个维度标签。
  - 种子 3 条：brand_agent / retail / mall；admin 可随时加新单元（如"特产批发"）。
  - 写入时自动填固定 code，不让用户选。

何时升级：
  - 如果未来需要"员工独立归属某单元"、"资金池独立"、"独立 RLS"，再走阶梯 1/2/3。
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OrgUnit(Base):
    __tablename__ = "org_units"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False
    )  # brand_agent / retail / mall / 未来新单元
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
