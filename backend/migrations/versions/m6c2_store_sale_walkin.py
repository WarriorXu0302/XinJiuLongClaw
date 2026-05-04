"""M6c.2: store_sales.customer_id 放开 NOT NULL + 加 walk-in 散客字段

决策 #3 散客支持：
- customer_id 允许 NULL（散客无会员账号）
- 新增 customer_walk_in_name / customer_walk_in_phone（可选文本记录，仅营销用）

Revision ID: m6c2walkin
Revises: m6c1adjusts
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa


revision = "m6c2walkin"
down_revision = "m6c1adjusts"
branch_labels = None
depends_on = None


def upgrade():
    # 1. store_sales.customer_id 放开 NOT NULL（散客无会员）
    op.alter_column(
        "store_sales", "customer_id",
        existing_type=sa.String(36),
        nullable=True,
    )
    # 2. store_sales 新增两列散客快照
    op.add_column(
        "store_sales",
        sa.Column("customer_walk_in_name", sa.String(100), nullable=True),
    )
    op.add_column(
        "store_sales",
        sa.Column("customer_walk_in_phone", sa.String(20), nullable=True),
    )
    # 3. store_sale_returns.customer_id 同步放开（散客原单退货）
    op.alter_column(
        "store_sale_returns", "customer_id",
        existing_type=sa.String(36),
        nullable=True,
    )


def downgrade():
    # 回滚前需先确认相关表无 NULL 行（有则需手工处理）
    op.alter_column(
        "store_sale_returns", "customer_id",
        existing_type=sa.String(36),
        nullable=False,
    )
    op.drop_column("store_sales", "customer_walk_in_phone")
    op.drop_column("store_sales", "customer_walk_in_name")
    op.alter_column(
        "store_sales", "customer_id",
        existing_type=sa.String(36),
        nullable=False,
    )
