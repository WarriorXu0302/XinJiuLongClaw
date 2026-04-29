"""M4a.5: commissions 表加 mall_order_id 字段

Revision ID: m4a2commissions
Revises: m4a1fulfilment
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa


revision = "m4a2commissions"
down_revision = "m4a1fulfilment"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "commissions",
        sa.Column(
            "mall_order_id", sa.String(36),
            sa.ForeignKey("mall_orders.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_commissions_mall_order", "commissions", ["mall_order_id"])


def downgrade():
    op.drop_index("ix_commissions_mall_order", table_name="commissions")
    op.drop_column("commissions", "mall_order_id")
