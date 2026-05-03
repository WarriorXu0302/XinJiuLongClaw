"""M5a.9: mall_hot_search_keywords 表（热搜词 admin 管理）

Revision ID: m5a9hotsrch
Revises: m5a8return
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa


revision = "m5a9hotsrch"
down_revision = "m5a8return"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mall_hot_search_keywords",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("keyword", sa.String(100), nullable=False, unique=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_mall_hot_search_keywords_active_sort",
        "mall_hot_search_keywords",
        ["is_active", "sort_order"],
    )
    # Seed 老硬编码的 5 个词，平滑切换
    op.execute("""
        INSERT INTO mall_hot_search_keywords (keyword, sort_order, is_active)
        VALUES ('飞天茅台', 1, true),
               ('五粮液', 2, true),
               ('青岛啤酒', 3, true),
               ('汾酒', 4, true),
               ('水井坊', 5, true)
        ON CONFLICT (keyword) DO NOTHING
    """)


def downgrade():
    op.drop_index(
        "ix_mall_hot_search_keywords_active_sort",
        table_name="mall_hot_search_keywords",
    )
    op.drop_table("mall_hot_search_keywords")
