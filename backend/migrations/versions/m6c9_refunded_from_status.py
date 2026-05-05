"""M6c.9: mall_orders 加 refunded_from_status 字段

修复 P1-6：partial_closed 订单批准退货后，profit_service 排除 refunded
导致上月坏账"凭空消失"。新字段记退货前状态，profit_service 把
refunded(from partial_closed) 的订单也算进利润聚合 + 坏账。

Revision ID: m6c9refundedfrom
Revises: m6c8storerefund
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa


revision = "m6c9refundedfrom"
down_revision = "m6c8storerefund"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "mall_orders",
        sa.Column("refunded_from_status", sa.String(30), nullable=True),
    )


def downgrade():
    op.drop_column("mall_orders", "refunded_from_status")
