"""M6c.1: Commission 加 is_adjustment + adjustment_source；salary_adjustments_pending 表

决策 #1 跨月退货追回：
- commissions 加 is_adjustment (bool) 标识"退货追回"负数行
- commissions 加 adjustment_source_commission_id 追溯原 Commission
- 新表 salary_adjustments_pending：工资不够扣时挂账，下月再扣

Revision ID: m6c1adjusts
Revises: m6b3slink
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa


revision = "m6c1adjusts"
down_revision = "m6b3slink"
branch_labels = None
depends_on = None


def upgrade():
    # 1. commissions 加 is_adjustment + adjustment_source_commission_id
    op.add_column(
        "commissions",
        sa.Column("is_adjustment", sa.Boolean(),
                  nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "commissions",
        sa.Column("adjustment_source_commission_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_commissions_adjustment_source",
        "commissions", "commissions",
        ["adjustment_source_commission_id"], ["id"],
    )
    op.create_index(
        "ix_commissions_emp_adjustment_status",
        "commissions",
        ["employee_id", "status"],
        postgresql_where=sa.text("is_adjustment = true"),
    )

    # 2. salary_adjustments_pending 表
    op.create_table(
        "salary_adjustments_pending",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "employee_id", sa.String(36),
            sa.ForeignKey("employees.id"), nullable=False,
        ),
        sa.Column("pending_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column(
            "source_salary_record_id", sa.String(36),
            sa.ForeignKey("salary_records.id"), nullable=False,
        ),
        sa.Column(
            "settled_in_salary_id", sa.String(36),
            sa.ForeignKey("salary_records.id"), nullable=True,
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "pending_amount > 0",
            name="ck_adjustment_pending_positive",
        ),
    )
    op.create_index(
        "ix_salary_adj_pending_employee",
        "salary_adjustments_pending", ["employee_id"],
    )
    op.create_index(
        "ix_salary_adj_pending_source",
        "salary_adjustments_pending", ["source_salary_record_id"],
    )
    op.create_index(
        "ix_salary_adj_pending_settled",
        "salary_adjustments_pending", ["settled_in_salary_id"],
    )
    # 便捷查询：员工未结清的挂账（按创建时间正序扣）
    op.create_index(
        "ix_salary_adj_pending_unsettled_by_emp",
        "salary_adjustments_pending",
        ["employee_id", "created_at"],
        postgresql_where=sa.text("settled_in_salary_id IS NULL"),
    )


def downgrade():
    op.drop_index("ix_salary_adj_pending_unsettled_by_emp",
                  table_name="salary_adjustments_pending")
    op.drop_index("ix_salary_adj_pending_settled",
                  table_name="salary_adjustments_pending")
    op.drop_index("ix_salary_adj_pending_source",
                  table_name="salary_adjustments_pending")
    op.drop_index("ix_salary_adj_pending_employee",
                  table_name="salary_adjustments_pending")
    op.drop_table("salary_adjustments_pending")

    op.drop_index("ix_commissions_emp_adjustment_status",
                  table_name="commissions")
    op.drop_constraint("fk_commissions_adjustment_source",
                       "commissions", type_="foreignkey")
    op.drop_column("commissions", "adjustment_source_commission_id")
    op.drop_column("commissions", "is_adjustment")
