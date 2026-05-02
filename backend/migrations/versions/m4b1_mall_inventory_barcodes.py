"""M4b: 商城出库扫码 — mall_inventory_barcodes 表

Revision ID: m4b1barcodes
Revises: m4d1salarymall
Create Date: 2026-04-30
"""
from alembic import op
import sqlalchemy as sa


revision = "m4b1barcodes"
down_revision = "m4d1salarymall"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mall_inventory_barcodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("barcode", sa.String(200), nullable=False),
        sa.Column("barcode_type", sa.String(20), nullable=False),  # bottle / case
        sa.Column(
            "sku_id",
            sa.Integer(),
            sa.ForeignKey("mall_product_skus.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("mall_products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            sa.String(36),
            sa.ForeignKey("mall_warehouses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("batch_no", sa.String(100), nullable=False),
        sa.Column("parent_barcode", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),  # in_stock / outbound / damaged
        sa.Column(
            "outbound_order_id",
            sa.String(36),
            sa.ForeignKey("mall_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "outbound_inventory_flow_id",
            sa.String(36),
            sa.ForeignKey("mall_inventory_flows.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("outbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "outbound_by_user_id",
            sa.String(36),
            sa.ForeignKey("mall_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cost_price", sa.Numeric(14, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("barcode", name="uq_mall_barcodes_barcode"),
    )
    op.create_index(
        "ix_mall_barcodes_barcode",
        "mall_inventory_barcodes",
        ["barcode"],
    )
    op.create_index(
        "ix_mall_barcodes_sku",
        "mall_inventory_barcodes",
        ["sku_id"],
    )
    op.create_index(
        "ix_mall_barcodes_warehouse",
        "mall_inventory_barcodes",
        ["warehouse_id"],
    )
    op.create_index(
        "ix_mall_barcodes_status",
        "mall_inventory_barcodes",
        ["status"],
    )
    op.create_index(
        "ix_mall_barcodes_batch",
        "mall_inventory_barcodes",
        ["batch_no"],
    )
    op.create_index(
        "ix_mall_barcodes_parent",
        "mall_inventory_barcodes",
        ["parent_barcode"],
    )


def downgrade() -> None:
    op.drop_index("ix_mall_barcodes_parent", table_name="mall_inventory_barcodes")
    op.drop_index("ix_mall_barcodes_batch", table_name="mall_inventory_barcodes")
    op.drop_index("ix_mall_barcodes_status", table_name="mall_inventory_barcodes")
    op.drop_index("ix_mall_barcodes_warehouse", table_name="mall_inventory_barcodes")
    op.drop_index("ix_mall_barcodes_sku", table_name="mall_inventory_barcodes")
    op.drop_index("ix_mall_barcodes_barcode", table_name="mall_inventory_barcodes")
    op.drop_table("mall_inventory_barcodes")
