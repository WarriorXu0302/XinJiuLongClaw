"""M6c.7: salary_records 加 historical_clawback_deduction 字段

修复 P0 bug：挂账扣款原来直接改 rec.total_pay，被 _recalc_salary_total 抹掉。
改为独立字段，_recalc_salary_total 也要扫进来。

Revision ID: m6c7clawbackded
Revises: m6c6adjustuniq
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa


revision = "m6c7clawbackded"
down_revision = "m6c6adjustuniq"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "salary_records",
        sa.Column(
            "historical_clawback_deduction", sa.Numeric(10, 2),
            nullable=False, server_default="0.00",
        ),
    )


def downgrade():
    op.drop_column("salary_records", "historical_clawback_deduction")
