"""mall M3: 购物车 + 订单 + 订单项 + 抢单日志 + inventory qty >= 0 CHECK

Revision ID: m3a1mallorders
Revises: m2a1mallcatalog
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "m3a1mallorders"
down_revision = "m2a1mallcatalog"
branch_labels = None
depends_on = None


def upgrade():
    # =========================================================================
    # 给 mall_inventory.quantity 加 CHECK >= 0（修并发扣减潜在负值）
    # =========================================================================
    op.create_check_constraint(
        "ck_mall_inventory_qty_non_negative",
        "mall_inventory",
        "quantity >= 0",
    )

    # =========================================================================
    # mall_cart_items
    # =========================================================================
    op.create_table(
        "mall_cart_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer,
                  sa.ForeignKey("mall_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku_id", sa.Integer,
                  sa.ForeignKey("mall_product_skus.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("selected", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "sku_id", name="uq_mall_cart_user_sku"),
        sa.CheckConstraint("quantity > 0", name="ck_mall_cart_quantity_positive"),
    )
    op.create_index("ix_mall_cart_user", "mall_cart_items", ["user_id"])

    # =========================================================================
    # mall_orders
    # =========================================================================
    op.create_table(
        "mall_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_no", sa.String(30), nullable=False),
        sa.Column("user_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("address_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("referrer_salesman_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("assigned_salesman_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending_assignment"),
        sa.Column("payment_status", sa.String(30), nullable=False, server_default="unpaid"),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("shipping_fee", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("pay_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("received_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("profit_ledger_posted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("commission_posted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("remarks", sa.Text, nullable=True),
        sa.Column("cancellation_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("order_no", name="uq_mall_orders_order_no"),
    )
    op.create_index("ix_mall_orders_user_status", "mall_orders", ["user_id", "status"])
    op.create_index("ix_mall_orders_assigned", "mall_orders", ["assigned_salesman_id"])
    op.create_index("ix_mall_orders_referrer", "mall_orders", ["referrer_salesman_id"])
    op.create_index("ix_mall_orders_status_created", "mall_orders", ["status", "created_at"])

    # =========================================================================
    # mall_order_items
    # =========================================================================
    op.create_table(
        "mall_order_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(36),
                  sa.ForeignKey("mall_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer,
                  sa.ForeignKey("mall_products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sku_id", sa.Integer,
                  sa.ForeignKey("mall_product_skus.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("brand_id", sa.String(36),
                  sa.ForeignKey("brands.id"), nullable=True),
        sa.Column("sku_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("cost_price_snapshot", sa.Numeric(14, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("quantity > 0", name="ck_mall_order_items_qty_positive"),
    )
    op.create_index("ix_mall_order_items_order", "mall_order_items", ["order_id"])
    op.create_index("ix_mall_order_items_brand", "mall_order_items", ["brand_id"])

    # =========================================================================
    # mall_order_claim_logs
    # =========================================================================
    op.create_table(
        "mall_order_claim_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(36),
                  sa.ForeignKey("mall_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("from_salesman_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("to_salesman_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("operator_id", sa.String(36), nullable=True),
        sa.Column("operator_type", sa.String(20), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mall_order_claim_logs_order", "mall_order_claim_logs", ["order_id"])


def downgrade():
    op.drop_index("ix_mall_order_claim_logs_order", table_name="mall_order_claim_logs")
    op.drop_table("mall_order_claim_logs")

    op.drop_index("ix_mall_order_items_brand", table_name="mall_order_items")
    op.drop_index("ix_mall_order_items_order", table_name="mall_order_items")
    op.drop_table("mall_order_items")

    for ix in ["ix_mall_orders_status_created", "ix_mall_orders_referrer", "ix_mall_orders_assigned", "ix_mall_orders_user_status"]:
        op.drop_index(ix, table_name="mall_orders")
    op.drop_table("mall_orders")

    op.drop_index("ix_mall_cart_user", table_name="mall_cart_items")
    op.drop_table("mall_cart_items")

    op.drop_constraint("ck_mall_inventory_qty_non_negative", "mall_inventory", type_="check")
