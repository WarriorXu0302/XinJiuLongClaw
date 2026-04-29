"""
Mall 订单域模型（M3 范围：购物车 + 订单 + 订单项 + 抢单日志）。

M4 再建的：MallPayment / MallShipment / MallCustomerSkipLog / MallSkipAlert / Attachments。

关键业务规则：
  - MallOrder.referrer_salesman_id：下单瞬间从 user.referrer_salesman_id 复制，永不变动
  - MallOrder.assigned_salesman_id：当前配送业务员；nullable，claim 后非空
  - MallOrder.address_snapshot：JSONB 快照，避免地址改动影响历史订单
  - MallOrder.profit_ledger_posted / commission_posted：幂等标志（M4）
  - MallOrderItem.brand_id：下单时固化（跨品牌订单按 item 分账）
  - MallOrderItem.cost_price_snapshot：扣库存时从 MallInventory.avg_cost_price 快照
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mall.base import MallOrderStatus


# =============================================================================
# MallCartItem
# =============================================================================

class MallCartItem(Base):
    """购物车。同一用户同一 SKU 一条（UniqueConstraint 保证）。"""

    __tablename__ = "mall_cart_items"
    __table_args__ = (
        UniqueConstraint("user_id", "sku_id", name="uq_mall_cart_user_sku"),
        Index("ix_mall_cart_user", "user_id"),
        CheckConstraint("quantity > 0", name="ck_mall_cart_quantity_positive"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mall_users.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mall_products.id", ondelete="CASCADE"), nullable=False
    )
    sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mall_product_skus.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(), nullable=True
    )


# =============================================================================
# MallOrder
# =============================================================================

class MallOrder(Base):
    """订单主表。"""

    __tablename__ = "mall_orders"
    __table_args__ = (
        UniqueConstraint("order_no", name="uq_mall_orders_order_no"),
        Index("ix_mall_orders_user_status", "user_id", "status"),
        Index("ix_mall_orders_assigned", "assigned_salesman_id"),
        Index("ix_mall_orders_referrer", "referrer_salesman_id"),
        Index("ix_mall_orders_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # 对外展示的业务单号（用户可读），格式 MO + yyyymmdd + 6位序号
    order_no: Mapped[str] = mapped_column(String(30), nullable=False)

    # ─── 归属 ───────────────────────────────────────────────
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=False
    )
    address_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # 下单瞬间从 user.referrer_salesman_id 复制，永不变动
    referrer_salesman_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=True
    )
    # 当前配送业务员；null = 待抢单
    assigned_salesman_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=True
    )

    # ─── 状态 ───────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(40), nullable=False,
        default=MallOrderStatus.PENDING_ASSIGNMENT.value,
    )
    payment_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unpaid"
    )

    # ─── 金额 ───────────────────────────────────────────────
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    shipping_fee: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    # pay_amount = total_amount + shipping_fee - discount_amount（应收）
    pay_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # received_amount：财务确认后的累计已收；M4 财务确认时累加
    received_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )

    # ─── 时间戳 ─────────────────────────────────────────────
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    shipped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ─── 幂等 flag（M4 用）─────────────────────────────────
    profit_ledger_posted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    commission_posted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    remarks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(), nullable=True
    )


# =============================================================================
# MallOrderItem
# =============================================================================

class MallOrderItem(Base):
    """订单明细。一个 SKU 一条。"""

    __tablename__ = "mall_order_items"
    __table_args__ = (
        Index("ix_mall_order_items_order", "order_id"),
        Index("ix_mall_order_items_brand", "brand_id"),
        CheckConstraint("quantity > 0", name="ck_mall_order_items_qty_positive"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mall_orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mall_products.id", ondelete="RESTRICT"), nullable=False
    )
    sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mall_product_skus.id", ondelete="RESTRICT"), nullable=False
    )

    # 下单时固化（跨品牌订单按 item 分账）
    brand_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("brands.id"), nullable=True
    )
    # 商品名/规格/主图/条码 快照，避免商品改动影响历史订单
    sku_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    # 扣库存时从 MallInventory.avg_cost_price 快照；null = 还没扣减（比如纯商城 SKU cost_price 是 NULL）
    cost_price_snapshot: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# =============================================================================
# MallOrderClaimLog
# =============================================================================

class MallOrderClaimLog(Base):
    """抢单/改派历史（M3 先建表，M4 真正写入）。"""

    __tablename__ = "mall_order_claim_logs"
    __table_args__ = (
        Index("ix_mall_order_claim_logs_order", "order_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mall_orders.id", ondelete="CASCADE"), nullable=False
    )
    # MallClaimAction 枚举：claim / release / reassign / admin_assign
    action: Mapped[str] = mapped_column(String(20), nullable=False)

    from_salesman_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("mall_users.id", ondelete="SET NULL"), nullable=True
    )
    to_salesman_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("mall_users.id", ondelete="SET NULL"), nullable=True
    )
    # 操作人可能是业务员自己（mall_user）或管理员（erp user）
    operator_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    operator_type: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # mall_user / erp_user

    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
