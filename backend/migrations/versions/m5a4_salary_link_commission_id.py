"""M5a.4: salary_order_links 加 commission_id，支持同 mall_order 多笔 commission（partial_closed 恢复后的 top-up）

Revision ID: m5a4salarycom
Revises: m5a3consumerdel
Create Date: 2026-05-02

原 `uq_mall_order_commission_once (mall_order_id, is_manager_share)` 只允许
单 mall_order 挂一笔非经理分成 link，导致 partial_closed 恢复后追加的 commission
被工资单扫入逻辑中"已关联"短路过滤掉，永远发不出去。

改动：
  - 加 commission_id nullable FK
  - 删旧 uq，改用 (mall_order_id, commission_id, is_manager_share) —— 按具体 commission 条目去重
    (B2B 的 order_id 约束保持不变，因为 B2B 一单一提成没有增量场景)
"""
from alembic import op
import sqlalchemy as sa


revision = "m5a4salarycom"
down_revision = "m5a3consumerdelete"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "salary_order_links",
        sa.Column("commission_id", sa.String(36),
                  sa.ForeignKey("commissions.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index(
        "ix_salary_order_links_commission", "salary_order_links",
        ["commission_id"],
    )
    # 把旧的 mall 唯一约束换成按 commission_id 去重
    op.drop_constraint(
        "uq_mall_order_commission_once", "salary_order_links", type_="unique"
    )
    op.create_unique_constraint(
        "uq_mall_commission_linked_once", "salary_order_links",
        ["mall_order_id", "commission_id", "is_manager_share"],
    )


def downgrade():
    op.drop_constraint("uq_mall_commission_linked_once", "salary_order_links", type_="unique")
    op.create_unique_constraint(
        "uq_mall_order_commission_once", "salary_order_links",
        ["mall_order_id", "is_manager_share"],
    )
    op.drop_index("ix_salary_order_links_commission", table_name="salary_order_links")
    op.drop_column("salary_order_links", "commission_id")
