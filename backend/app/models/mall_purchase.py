"""商城/门店采购 ORM models。

设计原则（和 ERP PurchaseOrder 分离）：
  - scope='mall' 入 mall_warehouses + 付款扣 MALL_MASTER
  - scope='store' 入 warehouses(warehouse_type='store') + 付款扣 STORE_MASTER
  - 不受 brand_ids RLS 限制（mall/store 采购跨品牌）
  - 审批流和 ERP 采购一致：pending → approved → paid → received → completed
  - items 指向 mall_product_sku（mall 场景）
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.mall.inventory import MallWarehouse
    from app.models.mall.product import MallProduct, MallProductSku
    from app.models.product import Account, Supplier, Warehouse
    from app.models.user import Employee


class MallPurchaseOrder(Base):
    """商城 / 门店采购单。

    - scope='mall'：入 mall 仓，付款扣 MALL_MASTER
    - scope='store'：入 ERP store 仓（warehouse_type='store'），付款扣 STORE_MASTER
    """

    __tablename__ = "mall_purchase_orders"
    __table_args__ = (
        CheckConstraint("scope IN ('mall', 'store')", name="ck_mpo_scope"),
        CheckConstraint(
            # 入库目标按 scope 互斥
            "(scope = 'mall' AND mall_warehouse_id IS NOT NULL AND store_warehouse_id IS NULL)"
            " OR "
            "(scope = 'store' AND store_warehouse_id IS NOT NULL AND mall_warehouse_id IS NULL)",
            name="ck_mpo_warehouse_exclusive",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    po_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )

    # 采购维度
    scope: Mapped[str] = mapped_column(String(10), nullable=False)  # mall | store
    # 经营单元（scope=mall → mall, scope=store → retail，create_po 里自动填）
    org_unit_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("org_units.id"), nullable=False, index=True,
    )
    supplier_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("suppliers.id"), nullable=False
    )
    # mall 入库
    mall_warehouse_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("mall_warehouses.id"), nullable=True
    )
    # store 入库（复用 ERP warehouses 表，type=store 的仓）
    store_warehouse_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("warehouses.id"), nullable=True
    )

    # 付款（只用 cash 一种，不走 f_class/financing —— 商城/门店没有厂家返利场景）
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    cash_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    cash_account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=True
    )

    voucher_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 审批流（和 ERP PO 对齐）
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )  # pending → approved → paid → received → completed / cancelled

    operator_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    approved_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    paid_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    received_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    received_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    expected_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(), nullable=True
    )

    supplier: Mapped["Supplier"] = relationship("Supplier", lazy="selectin")
    mall_warehouse: Mapped[Optional["MallWarehouse"]] = relationship(
        "MallWarehouse", lazy="selectin"
    )
    store_warehouse: Mapped[Optional["Warehouse"]] = relationship(
        "Warehouse", foreign_keys=[store_warehouse_id], lazy="selectin"
    )
    cash_account: Mapped[Optional["Account"]] = relationship(
        "Account", foreign_keys=[cash_account_id], lazy="selectin"
    )
    items: Mapped[list["MallPurchaseOrderItem"]] = relationship(
        "MallPurchaseOrderItem",
        back_populates="purchase_order",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class MallPurchaseOrderItem(Base):
    """商城/门店采购明细。

    scope='mall' → 明细必传 mall_sku_id
    scope='store' → 门店也是卖 mall 商品（门店仓=卖商城库存的仓），同样传 mall_sku_id
                    （后续若门店有独立 SKU 场景再扩展 product_id 字段）
    """

    __tablename__ = "mall_purchase_order_items"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    po_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("mall_purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 采购的 SKU
    mall_sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mall_product_skus.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(default=0)
    quantity_unit: Mapped[str] = mapped_column(String(10), default="瓶")
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    purchase_order: Mapped["MallPurchaseOrder"] = relationship(
        "MallPurchaseOrder", back_populates="items"
    )
    sku: Mapped["MallProductSku"] = relationship(
        "MallProductSku", lazy="selectin"
    )
