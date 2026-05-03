"""门店零售销售（青花郎/五粮液/华致名酒库/鑫久酒专卖店）

业务模型：
  - 门店即 ERP `warehouses` 中 `warehouse_type='store'` 的仓
  - 店员（employees.position='cashier'）通过 mall_user(assigned_store_id=X) 进入小程序收银
  - 收银流程：输入客户 → 扫码 → 输入售价（必须在 product 区间内）→ 选付款方式 → 提交
  - 每瓶一行明细：记录售价 + 成本快照 + 利润 + 提成（每店员每商品一个 rate_on_profit）
  - 扫码即成交：条码 IN_STOCK → OUTBOUND，Inventory 扣减，商品销量累加
  - 成交数据进 ERP 利润台账（ProfitLedger 新科目 retail_sale_profit）+ commission pending

关键字段：
  - store_sales.store_id: 门店仓 warehouse.id
  - store_sales.cashier_employee_id: 扫码的店员（提成归属）
  - store_sales.customer_id: 消费者 mall_users.id（必填）
  - store_sales.payment_method: cash/wechat/alipay/card（不允许 credit 赊账）
  - store_sale_items.cost_price_snapshot: 从 InventoryBarcode 关联 Inventory.cost_price
  - store_sale_items.profit = (sale_price - cost_price_snapshot)
  - store_sale_items.commission_amount = profit * rate_on_profit

状态机：
  仅一个终态 = completed（没审批流，扫码即完成）
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
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


class StoreSale(Base):
    """门店零售销售单。

    创建即 completed（不走审批）。commission 和 profit 同步生成。
    """

    __tablename__ = "store_sales"
    __table_args__ = (
        Index("ix_store_sales_store", "store_id"),
        Index("ix_store_sales_cashier", "cashier_employee_id"),
        Index("ix_store_sales_customer", "customer_id"),
        Index("ix_store_sales_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sale_no: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False,
        comment="SS-YYYYMMDD-HHMMSS-xxxxxx",
    )

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("warehouses.id"), nullable=False,
        comment="门店仓（warehouse_type=store）",
    )
    cashier_employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False,
        comment="扫码出库的店员，提成归属",
    )
    customer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mall_users.id"), nullable=False,
        comment="消费者（必填，不允许匿名）",
    )

    # 金额（从 items 累加冗余写入）
    total_sale_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    total_profit: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    total_commission: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    total_bottles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 付款方式：cash / wechat / alipay / card（不允许 credit）
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)

    # 备注 + 状态
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="completed",
        comment="完成即终态，无审批；保留字段预留未来作废/退货用",
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class StoreSaleItem(Base):
    """门店销售明细，每瓶一行（条码粒度）。"""

    __tablename__ = "store_sale_items"
    __table_args__ = (
        Index("ix_store_sale_items_sale", "sale_id"),
        Index("ix_store_sale_items_barcode", "barcode"),
        Index("ix_store_sale_items_product", "product_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sale_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("store_sales.id", ondelete="CASCADE"), nullable=False,
    )

    # 条码（对应 inventory_barcodes.barcode；出库时已改 status=outbound）
    barcode: Mapped[str] = mapped_column(String(200), nullable=False)
    product_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("products.id"), nullable=False,
    )
    batch_no_snapshot: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="出库时源 Inventory 的 batch_no 快照",
    )

    # 售价（店员输入，必须在 product.min_sale_price..max_sale_price 之间）
    sale_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    # 成本快照（瓶级，从 Inventory.cost_price 按 batch 取）
    cost_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    # 利润 = sale_price - cost_price_snapshot（写入时计算好）
    profit: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    # 提成计算（快照）
    # rate_on_profit 从 retail_commission_rates(employee_id, product_id) 查；
    # commission_amount = profit * rate_on_profit；
    # 关联的 Commission.id 单独挂 ERP 工资单
    rate_on_profit_snapshot: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 4), nullable=True,
        comment="成交时锁定的提成率（= retail_commission_rates 当时的值）",
    )
    commission_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0")
    )
    commission_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("commissions.id"), nullable=True,
        comment="生成的 Commission 关联（月结挂工资单）",
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class RetailCommissionRate(Base):
    """门店店员个性化提成率（每员工 × 每商品）。

    查询：service 从 (employee_id, product_id) 查 rate_on_profit；找不到 → 抛 400
    让管理员先配置。
    """

    __tablename__ = "retail_commission_rates"
    __table_args__ = (
        UniqueConstraint("employee_id", "product_id",
                         name="uq_retail_commission_emp_product"),
        Index("ix_retail_commission_employee", "employee_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    employee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False,
    )
    product_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("products.id"), nullable=False,
    )
    # 提成率（对利润的百分比，0.0000–1.0000）
    rate_on_profit: Mapped[Decimal] = mapped_column(
        Numeric(7, 4), nullable=False,
        comment="对每瓶利润的提成率，如 0.1500 = 15%",
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        onupdate=func.now(), nullable=True
    )
