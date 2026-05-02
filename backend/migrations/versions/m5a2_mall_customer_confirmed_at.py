"""M5a.2: mall_orders.customer_confirmed_at（C 端确认收货时间）

Revision ID: m5a2consumerconfirm
Revises: m5a1auditmalluser
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa


revision = "m5a2consumerconfirm"
down_revision = "m5a1auditmalluser"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "mall_orders",
        sa.Column("customer_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("mall_orders", "customer_confirmed_at")
