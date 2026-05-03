"""仓库调拨单（跨 ERP 仓 + mall 仓）

业务规则：
  - 品牌主仓（warehouse_type='main' AND brand_id NOT NULL）**不参与调拨**——出入都禁止
  - 所有商品第一次入仓必须走采购订单；调拨是已入仓之后的仓间流转
  - 白酒每瓶必须扫厂家防伪码（条码过户粒度，不允许按数量散装）
  - ERP 仓 ↔ mall 仓 可以跨端调拨，条码迁移到对端的 *_barcodes 表
  - 审批策略：
      * 同品牌内部（两仓 brand_id 相同且都非 mall）→ 免审，直接 executed
      * 跨品牌 / ERP↔mall / 涉任何 mall 仓 → 必审（boss/finance）

状态机：
  pending_scan ─submit→ pending_approval ─approve→ approved ─execute→ executed
                    │                    ─reject→ rejected（终态）
                    └─cancel→ cancelled（源仓条码解锁回 in_stock）

  免审场景直接 pending_scan ─execute→ executed（跳过审批）
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# 状态值（业务枚举）
TRANSFER_STATUS_PENDING_SCAN = "pending_scan"           # 扫码中 / 已保存未提交
TRANSFER_STATUS_PENDING_APPROVAL = "pending_approval"   # 已提交待审批
TRANSFER_STATUS_APPROVED = "approved"                   # 已批准待执行
TRANSFER_STATUS_EXECUTED = "executed"                   # 已执行（终态）
TRANSFER_STATUS_REJECTED = "rejected"                   # 已驳回（终态）
TRANSFER_STATUS_CANCELLED = "cancelled"                 # 已取消（终态，条码解锁）

# 仓端类型
WAREHOUSE_SIDE_ERP = "erp"
WAREHOUSE_SIDE_MALL = "mall"


class WarehouseTransfer(Base):
    """仓库调拨主单。支持 ERP ↔ mall 跨端。

    源仓 / 目标仓 各存 (side, warehouse_id) 二元组：
      - side='erp' → warehouse_id 指 warehouses.id
      - side='mall' → warehouse_id 指 mall_warehouses.id
    不建 FK（跨表多态引用），应用层 + service 层校验存在性。
    """

    __tablename__ = "warehouse_transfers"
    __table_args__ = (
        Index("ix_wh_transfers_status", "status"),
        Index("ix_wh_transfers_source", "source_side", "source_warehouse_id"),
        Index("ix_wh_transfers_dest", "dest_side", "dest_warehouse_id"),
        Index("ix_wh_transfers_created", "created_at"),
        CheckConstraint(
            "source_side IN ('erp','mall') AND dest_side IN ('erp','mall')",
            name="ck_wh_transfers_side_values",
        ),
        CheckConstraint(
            "NOT (source_side = dest_side AND source_warehouse_id = dest_warehouse_id)",
            name="ck_wh_transfers_src_not_dest",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transfer_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False,
        comment="TR-YYYYMMDD-HHMMSS-xxxxxx 格式业务单号",
    )

    # 源仓
    source_side: Mapped[str] = mapped_column(String(10), nullable=False)
    source_warehouse_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # 目标仓
    dest_side: Mapped[str] = mapped_column(String(10), nullable=False)
    dest_warehouse_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # 状态
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=TRANSFER_STATUS_PENDING_SCAN,
    )
    # 是否需要审批（创建时根据业务规则决定）
    requires_approval: Mapped[bool] = mapped_column(nullable=False, default=True)

    # 发起人（ERP employee.id；mall 仓管发起也用对应 linked_employee_id）
    initiator_employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )

    # 审批
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approver_employee_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 执行
    executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 说明（业务备注）
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 统计（写时冗余，读时快）
    total_bottles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True,
        comment="所有条码成本合计（从源端快照）",
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(), nullable=True
    )


class WarehouseTransferItem(Base):
    """调拨明细：每个条码一行。

    跨端时：
      - source_barcode 来自源端的 inventory_barcodes 或 mall_inventory_barcodes
      - 执行时：源端 barcode 软删（status=transferred）或直接 DELETE；目标端新建一行
      - cost_price_snapshot 从源条码读，跨端时带到目标端
    """

    __tablename__ = "warehouse_transfer_items"
    __table_args__ = (
        Index("ix_wh_transfer_items_transfer", "transfer_id"),
        Index("ix_wh_transfer_items_barcode", "barcode"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transfer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("warehouse_transfers.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 条码（不建 FK，因为可能指向 inventory_barcodes 或 mall_inventory_barcodes）
    barcode: Mapped[str] = mapped_column(String(200), nullable=False)
    # product 引用（ERP product.id；mall 侧存 MallProduct.id 的字符串形式统一成字符串）
    product_ref: Mapped[str] = mapped_column(
        String(36), nullable=False,
        comment="ERP 侧 products.id；mall 侧 mall_products.id 的字符串",
    )
    # SKU ref（仅 mall 侧有意义，ERP 可空）
    sku_ref: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True,
        comment="mall 侧 mall_product_skus.id；ERP 侧无此概念可空",
    )

    # 源端成本快照（用于目标端加权平均成本计算 / 对账）
    cost_price_snapshot: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    # 源端批次号（ERP→mall 时带过去辅助追溯；mall→ERP 时给 ERP 用）
    batch_no_snapshot: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
