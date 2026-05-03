"""M6b.3: salary_order_links 加 store_sale_id 支持门店零售提成入工资单

改动：
  - 加列 salary_order_links.store_sale_id → store_sales.id（nullable）
  - 旧 CHECK ck_salary_order_link_exclusive_ref（"order_id XOR mall_order_id"）
    → 新 CHECK：三者恰有一个非空
  - UniqueConstraint(store_sale_id, commission_id) 防止同一门店提成挂两次工资单

Revision ID: m6b3slink
Revises: m6b2storret
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa


revision = "m6b3slink"
down_revision = "m6b2storret"
branch_labels = None
depends_on = None


def upgrade():
    # 1. 加 store_sale_id 列
    op.add_column(
        "salary_order_links",
        sa.Column("store_sale_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_salary_order_links_store_sale",
        "salary_order_links", "store_sales",
        ["store_sale_id"], ["id"],
    )

    # 2. 删旧 CHECK，加新 CHECK（三选一恰一个非空）
    op.drop_constraint(
        "ck_salary_order_link_exclusive_ref",
        "salary_order_links", type_="check",
    )
    op.create_check_constraint(
        "ck_salary_order_link_exclusive_ref",
        "salary_order_links",
        "("
        "(order_id IS NOT NULL)::int + "
        "(mall_order_id IS NOT NULL)::int + "
        "(store_sale_id IS NOT NULL)::int"
        ") = 1",
    )

    # 3. 加 UNIQUE(store_sale_id, commission_id) 防重复入工资单
    op.create_unique_constraint(
        "uq_store_sale_commission_linked_once",
        "salary_order_links",
        ["store_sale_id", "commission_id"],
    )


def downgrade():
    op.drop_constraint(
        "uq_store_sale_commission_linked_once",
        "salary_order_links", type_="unique",
    )
    op.drop_constraint(
        "ck_salary_order_link_exclusive_ref",
        "salary_order_links", type_="check",
    )
    op.create_check_constraint(
        "ck_salary_order_link_exclusive_ref",
        "salary_order_links",
        "(order_id IS NOT NULL AND mall_order_id IS NULL) "
        "OR (order_id IS NULL AND mall_order_id IS NOT NULL)",
    )
    op.drop_constraint(
        "fk_salary_order_links_store_sale",
        "salary_order_links", type_="foreignkey",
    )
    op.drop_column("salary_order_links", "store_sale_id")
