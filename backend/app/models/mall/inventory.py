"""
Mall 仓库 + 库存模型。

- MallWarehouse：商城仓（manager_user_id 指向 mall_users.id 且必为 salesman）
- MallInventory：每个仓 × SKU 一条记录，UniqueConstraint
- MallInventoryFlow：出入库流水（类型 in/out/adjust/transfer_in/transfer_out/loss）

加权平均成本：MallInventory.avg_cost_price 只在 in/transfer_in 时更新；
退货/调拨/盘亏走独立流水，用原单成本记录，不动 avg_cost_price。
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# =============================================================================
# MallWarehouse
# =============================================================================

class MallWarehouse(Base):
    """商城仓。manager_user_id 必须指向业务员（user_type=salesman）。"""

    __tablename__ = "mall_warehouses"
    __table_args__ = (
        Index("ix_mall_warehouses_code", "code", unique=True),
        Index("ix_mall_warehouses_manager", "manager_user_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # 指向业务员；应用层 assert_is_salesman 校验，M4 上 T1 触发器兜底
    manager_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(), nullable=True
    )


# =============================================================================
# MallInventory
# =============================================================================

class MallInventory(Base):
    """仓 × SKU 库存汇总。每次出入库都要更新这里的 quantity 和（必要时）avg_cost_price。"""

    __tablename__ = "mall_inventory"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "sku_id", name="uq_mall_inventory_wh_sku"),
        Index("ix_mall_inventory_sku", "sku_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    warehouse_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mall_warehouses.id", ondelete="CASCADE"), nullable=False
    )
    sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mall_product_skus.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 动态加权平均成本：入库时 = (旧qty×旧avg + 新入qty×新价) / (旧qty + 新入qty)
    avg_cost_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )

    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(), nullable=True
    )


# =============================================================================
# MallInventoryFlow
# =============================================================================

class MallInventoryFlow(Base):
    """出入库流水。每次变动一条，便于审计和成本溯源。"""

    __tablename__ = "mall_inventory_flows"
    __table_args__ = (
        Index("ix_mall_inventory_flows_inv", "inventory_id"),
        Index("ix_mall_inventory_flows_type", "flow_type"),
        Index("ix_mall_inventory_flows_ref", "ref_type", "ref_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    inventory_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mall_inventory.id", ondelete="RESTRICT"), nullable=False
    )
    flow_type: Mapped[str] = mapped_column(String(20), nullable=False)  # MallInventoryFlowType
    # 变动数量；可为负（出库、盘亏）
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)

    # 关联来源单据（order / purchase / transfer / adjust）
    ref_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    ref_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# =============================================================================
# MallInventoryBarcode
# =============================================================================

class MallInventoryBarcode(Base):
    """单瓶/单箱级别条码。

    对齐 ERP InventoryBarcode：支持扫码出库核销、状态流转（IN_STOCK → OUTBOUND）。
    mall 侧简化：
      - 第一版只用 BOTTLE（1 码 = 1 瓶），CASE 预留
      - 入库时由采购/种子脚本批量生成条码
      - 出库时业务员在小程序扫码，后端逐码核销
      - 支持 parent_barcode 关联（CASE → BOTTLE 批量拆箱）
    """

    __tablename__ = "mall_inventory_barcodes"
    __table_args__ = (
        Index("ix_mall_barcodes_sku", "sku_id"),
        Index("ix_mall_barcodes_warehouse", "warehouse_id"),
        Index("ix_mall_barcodes_status", "status"),
        Index("ix_mall_barcodes_batch", "batch_no"),
        Index("ix_mall_barcodes_parent", "parent_barcode"),
        # ship_order / ship_mode 探测仓内是否有 IN_STOCK 条码用
        Index("ix_mall_barcodes_sku_status_wh", "sku_id", "status", "warehouse_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    barcode: Mapped[str] = mapped_column(
        String(200), unique=True, index=True, nullable=False
    )
    barcode_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # MallInventoryBarcodeType
    sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mall_product_skus.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mall_products.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mall_warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    batch_no: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    parent_barcode: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True, index=True
    )
    # 状态：in_stock / outbound / damaged
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # 出库时回填：关联 mall_order + 流水
    outbound_order_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("mall_orders.id", ondelete="SET NULL"), nullable=True
    )
    outbound_inventory_flow_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("mall_inventory_flows.id", ondelete="SET NULL"), nullable=True
    )
    outbound_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    outbound_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("mall_users.id", ondelete="SET NULL"), nullable=True
    )

    cost_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(), nullable=True
    )
