"""M5a.3: mall_orders.consumer_deleted_at（C 端软删标记）

Revision ID: m5a3consumerdelete
Revises: m5a2consumerconfirm
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa


revision = "m5a3consumerdelete"
down_revision = "m5a2consumerconfirm"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "mall_orders",
        sa.Column("consumer_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("mall_orders", "consumer_deleted_at")
