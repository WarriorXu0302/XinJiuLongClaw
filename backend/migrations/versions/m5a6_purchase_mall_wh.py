"""M5a.6: purchase_orders 加跨仓字段 target_warehouse_type / mall_warehouse_id

Revision ID: m5a6purchwh
Revises: m5a5mallapp
Create Date: 2026-05-03

采购跨仓：一个 PO 可指定入 ERP 仓或 mall 仓。
  - target_warehouse_type: 'erp_warehouse' | 'mall_warehouse'，default 'erp_warehouse'
  - mall_warehouse_id: FK mall_warehouses.id，nullable（mall 仓场景用）
receive_purchase_order service 根据此字段分支到 inventory 或 mall_inventory。
"""
from alembic import op
import sqlalchemy as sa


revision = "m5a6purchwh"
down_revision = "m5a5mallapp"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "purchase_orders",
        sa.Column(
            "target_warehouse_type", sa.String(20),
            nullable=False, server_default="erp_warehouse",
        ),
    )
    op.add_column(
        "purchase_orders",
        sa.Column(
            "mall_warehouse_id", sa.String(36),
            sa.ForeignKey("mall_warehouses.id"), nullable=True,
        ),
    )


def downgrade():
    op.drop_column("purchase_orders", "mall_warehouse_id")
    op.drop_column("purchase_orders", "target_warehouse_type")
