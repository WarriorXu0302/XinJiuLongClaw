"""M4d.1: salary_order_links 加 mall_order_id，order_id 放宽为 nullable

Revision ID: m4d1salarymall
Revises: m4c1notifmall
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa


revision = "m4d1salarymall"
down_revision = "m4c1notifmall"
branch_labels = None
depends_on = None


def upgrade():
    # order_id 改 nullable
    op.alter_column(
        "salary_order_links", "order_id",
        existing_type=sa.String(36),
        nullable=True,
    )
    # 新增 mall_order_id
    op.add_column(
        "salary_order_links",
        sa.Column("mall_order_id", sa.String(36),
                  sa.ForeignKey("mall_orders.id"), nullable=True),
    )
    # brand_id 也放宽 nullable（mall 订单可能无品牌）
    op.alter_column(
        "salary_order_links", "brand_id",
        existing_type=sa.String(36),
        nullable=True,
    )
    op.create_index(
        "ix_salary_order_links_mall_order", "salary_order_links",
        ["mall_order_id"],
    )
    op.create_unique_constraint(
        "uq_mall_order_commission_once", "salary_order_links",
        ["mall_order_id", "is_manager_share"],
    )
    op.create_check_constraint(
        "ck_salary_order_link_exclusive_ref", "salary_order_links",
        "(order_id IS NOT NULL AND mall_order_id IS NULL) OR (order_id IS NULL AND mall_order_id IS NOT NULL)",
    )


def downgrade():
    op.drop_constraint("ck_salary_order_link_exclusive_ref", "salary_order_links", type_="check")
    op.drop_constraint("uq_mall_order_commission_once", "salary_order_links", type_="unique")
    op.drop_index("ix_salary_order_links_mall_order", table_name="salary_order_links")
    op.drop_column("salary_order_links", "mall_order_id")
    op.alter_column(
        "salary_order_links", "brand_id",
        existing_type=sa.String(36),
        nullable=False,
    )
    op.alter_column(
        "salary_order_links", "order_id",
        existing_type=sa.String(36),
        nullable=False,
    )
