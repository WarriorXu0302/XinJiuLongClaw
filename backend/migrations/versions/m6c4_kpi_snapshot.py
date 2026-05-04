"""M6c.4: mall_monthly_kpi_snapshot 表（决策 #2 月榜快照 vs 实时双显）

业务：月初 1 号自动冻结上月业务员 KPI（GMV/订单数/提成）存入本表；
后续客户退货不影响快照数字，老板发奖金时看快照，看趋势看实时。

Revision ID: m6c4kpisnap
Revises: m6c3netsales
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa


revision = "m6c4kpisnap"
down_revision = "m6c3netsales"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mall_monthly_kpi_snapshot",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("employee_id", sa.String(36),
                  sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("gmv", sa.Numeric(15, 2),
                  nullable=False, server_default="0"),
        sa.Column("order_count", sa.Integer(),
                  nullable=False, server_default="0"),
        sa.Column("commission_amount", sa.Numeric(15, 2),
                  nullable=False, server_default="0"),
        sa.Column("snapshot_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("employee_id", "period",
                            name="uq_mall_kpi_snap_emp_period"),
    )
    op.create_index(
        "ix_mall_kpi_snap_period",
        "mall_monthly_kpi_snapshot", ["period"],
    )
    op.create_index(
        "ix_mall_kpi_snap_employee",
        "mall_monthly_kpi_snapshot", ["employee_id"],
    )


def downgrade():
    op.drop_index("ix_mall_kpi_snap_employee",
                  table_name="mall_monthly_kpi_snapshot")
    op.drop_index("ix_mall_kpi_snap_period",
                  table_name="mall_monthly_kpi_snapshot")
    op.drop_table("mall_monthly_kpi_snapshot")
