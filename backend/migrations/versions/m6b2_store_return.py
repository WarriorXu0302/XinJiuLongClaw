"""M6b.2: 门店退货（整单退）

业务模型见 app/models/store_sale.py StoreSaleReturn / StoreSaleReturnItem。

- 店员发起 pending → admin/finance 审批 approved 或 rejected
- approved 时：条码 OUTBOUND→IN_STOCK + Inventory 回加 + StockFlow retail_return
  + Commission reversed + StoreSale.status=refunded

Revision ID: m6b2storret
Revises: m6b1storsal
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa


revision = "m6b2storret"
down_revision = "m6b1storsal"
branch_labels = None
depends_on = None


def upgrade():
    # 1. store_sale_returns：退货单头
    op.create_table(
        "store_sale_returns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("return_no", sa.String(50), nullable=False, unique=True),
        sa.Column(
            "original_sale_id", sa.String(36),
            sa.ForeignKey("store_sales.id"), nullable=False,
        ),
        sa.Column(
            "store_id", sa.String(36),
            sa.ForeignKey("warehouses.id"), nullable=False,
        ),
        sa.Column(
            "initiator_employee_id", sa.String(36),
            sa.ForeignKey("employees.id"), nullable=False,
        ),
        sa.Column(
            "customer_id", sa.String(36),
            sa.ForeignKey("mall_users.id"), nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(20),
            nullable=False, server_default="pending",
        ),
        sa.Column("refund_amount", sa.Numeric(15, 2),
                  nullable=False, server_default="0"),
        sa.Column("commission_reversal_amount", sa.Numeric(15, 2),
                  nullable=False, server_default="0"),
        sa.Column("total_bottles", sa.Integer(),
                  nullable=False, server_default="0"),
        sa.Column(
            "reviewer_employee_id", sa.String(36),
            sa.ForeignKey("employees.id"), nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_store_sale_returns_sale",
        "store_sale_returns", ["original_sale_id"],
    )
    op.create_index(
        "ix_store_sale_returns_store",
        "store_sale_returns", ["store_id"],
    )
    op.create_index(
        "ix_store_sale_returns_status",
        "store_sale_returns", ["status"],
    )
    op.create_index(
        "ix_store_sale_returns_created",
        "store_sale_returns", ["created_at"],
    )

    # 2. store_sale_return_items：每瓶一行
    op.create_table(
        "store_sale_return_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "return_id", sa.String(36),
            sa.ForeignKey("store_sale_returns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "original_item_id", sa.String(36),
            sa.ForeignKey("store_sale_items.id"), nullable=False,
        ),
        sa.Column("barcode", sa.String(200), nullable=False),
        sa.Column(
            "product_id", sa.String(36),
            sa.ForeignKey("products.id"), nullable=False,
        ),
        sa.Column("batch_no_snapshot", sa.String(100), nullable=True),
        sa.Column("sale_price_snapshot", sa.Numeric(15, 2), nullable=False),
        sa.Column("commission_reversal", sa.Numeric(15, 2),
                  nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_store_sale_return_items_return",
        "store_sale_return_items", ["return_id"],
    )
    op.create_index(
        "ix_store_sale_return_items_barcode",
        "store_sale_return_items", ["barcode"],
    )


def downgrade():
    op.drop_index("ix_store_sale_return_items_barcode", table_name="store_sale_return_items")
    op.drop_index("ix_store_sale_return_items_return", table_name="store_sale_return_items")
    op.drop_table("store_sale_return_items")

    op.drop_index("ix_store_sale_returns_created", table_name="store_sale_returns")
    op.drop_index("ix_store_sale_returns_status", table_name="store_sale_returns")
    op.drop_index("ix_store_sale_returns_store", table_name="store_sale_returns")
    op.drop_index("ix_store_sale_returns_sale", table_name="store_sale_returns")
    op.drop_table("store_sale_returns")
