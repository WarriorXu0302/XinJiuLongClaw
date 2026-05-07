"""m6cb: 建 mall_purchase_orders + mall_purchase_order_items 表

商城/门店采购独立（不和 ERP B2B 采购混同），跨品牌业务：
  - scope='mall' → 入 mall_warehouses + 扣 MALL_MASTER 账户
  - scope='store' → 入 warehouses(warehouse_type=store) + 扣 STORE_MASTER 账户
  - 不受 brand_ids RLS 限制（mall/store 本就跨品牌，不能用 B2B 品牌事业部规则约束）

Revision ID: 7da04a1ce06a
Revises: m6caaccts
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa


revision = "7da04a1ce06a"
down_revision = "m6caaccts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mall_purchase_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("po_no", sa.String(50), nullable=False),
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column("supplier_id", sa.String(36), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("mall_warehouse_id", sa.String(36), sa.ForeignKey("mall_warehouses.id"), nullable=True),
        sa.Column("store_warehouse_id", sa.String(36), sa.ForeignKey("warehouses.id"), nullable=True),
        sa.Column("total_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("cash_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("cash_account_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("voucher_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("operator_id", sa.String(36), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("approved_by", sa.String(36), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_by", sa.String(36), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_by", sa.String(36), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope IN ('mall', 'store')", name="ck_mpo_scope"),
        sa.CheckConstraint(
            "(scope = 'mall' AND mall_warehouse_id IS NOT NULL AND store_warehouse_id IS NULL)"
            " OR "
            "(scope = 'store' AND store_warehouse_id IS NOT NULL AND mall_warehouse_id IS NULL)",
            name="ck_mpo_warehouse_exclusive",
        ),
    )
    op.create_index(
        "ix_mall_purchase_orders_po_no",
        "mall_purchase_orders",
        ["po_no"],
        unique=True,
    )
    op.create_index(
        "ix_mall_purchase_orders_scope_status",
        "mall_purchase_orders",
        ["scope", "status"],
    )

    op.create_table(
        "mall_purchase_order_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "po_id", sa.String(36),
            sa.ForeignKey("mall_purchase_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mall_sku_id", sa.Integer(),
            sa.ForeignKey("mall_product_skus.id"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quantity_unit", sa.String(10), nullable=False, server_default="瓶"),
        sa.Column("unit_price", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_mall_purchase_order_items_po",
        "mall_purchase_order_items",
        ["po_id"],
    )


def downgrade():
    op.drop_index("ix_mall_purchase_order_items_po", table_name="mall_purchase_order_items")
    op.drop_table("mall_purchase_order_items")
    op.drop_index("ix_mall_purchase_orders_scope_status", table_name="mall_purchase_orders")
    op.drop_index("ix_mall_purchase_orders_po_no", table_name="mall_purchase_orders")
    op.drop_table("mall_purchase_orders")
