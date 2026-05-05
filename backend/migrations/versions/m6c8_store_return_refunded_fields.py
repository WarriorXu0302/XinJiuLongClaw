"""M6c.8: store_sale_returns 加 refunded_at / refund_method / refund_note

修复问题 #2：门店退货从一步到位（approve = refunded）改为两段式
approve → mark_refunded（和 mall_return 对齐，财务月底能查退款方式）。

Revision ID: m6c8storerefund
Revises: m6c7clawbackded
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa


revision = "m6c8storerefund"
down_revision = "m6c7clawbackded"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "store_sale_returns",
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "store_sale_returns",
        sa.Column("refund_method", sa.String(20), nullable=True),
    )
    op.add_column(
        "store_sale_returns",
        sa.Column("refund_note", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("store_sale_returns", "refund_note")
    op.drop_column("store_sale_returns", "refund_method")
    op.drop_column("store_sale_returns", "refunded_at")
