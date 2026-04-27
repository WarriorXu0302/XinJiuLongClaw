"""kpi_coefficient_rules + salary_records.kpi_rule_snapshot

Revision ID: c9e1a2b3d4f5
Revises: b5c8d4e9f2a1
Create Date: 2026-04-28

新表：kpi_coefficient_rules（按品牌配置完成率→系数规则，支持时间段留存历史）
新字段：salary_records.kpi_rule_snapshot（生成/重算时冻结当时规则集）

默认数据：为现有每个品牌 seed 两条"全线性"规则
  - [0, 0.5) mode=fixed fixed_value=0
  - [0.5, NULL) mode=linear
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c9e1a2b3d4f5"
down_revision = "b5c8d4e9f2a1"
branch_labels = None
depends_on = None


def upgrade():
    # 1. 新表
    op.create_table(
        "kpi_coefficient_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("brand_id", sa.String(36), sa.ForeignKey("brands.id", ondelete="CASCADE"), nullable=False),
        sa.Column("min_rate", sa.Numeric(6, 4), nullable=False),
        sa.Column("max_rate", sa.Numeric(6, 4), nullable=True),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("fixed_value", sa.Numeric(6, 4), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_kpi_rules_brand_id", "kpi_coefficient_rules", ["brand_id"])
    op.create_index("ix_kpi_rules_effective_from", "kpi_coefficient_rules", ["effective_from"])
    op.create_index("ix_kpi_rules_effective_to", "kpi_coefficient_rules", ["effective_to"])

    # 2. salary_records 加 kpi_rule_snapshot
    op.add_column(
        "salary_records",
        sa.Column("kpi_rule_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # 3. 为现有每个品牌 seed 默认规则（全线性：<50%=0，其余按完成率）
    op.execute(
        """
        INSERT INTO kpi_coefficient_rules (id, brand_id, min_rate, max_rate, mode, fixed_value, effective_from, notes)
        SELECT gen_random_uuid()::text, b.id, 0.0, 0.5, 'fixed', 0.0, CURRENT_DATE,
               '系统初始化默认规则：完成率 <50% 系数 0'
        FROM brands b
        """
    )
    op.execute(
        """
        INSERT INTO kpi_coefficient_rules (id, brand_id, min_rate, max_rate, mode, fixed_value, effective_from, notes)
        SELECT gen_random_uuid()::text, b.id, 0.5, NULL, 'linear', NULL, CURRENT_DATE,
               '系统初始化默认规则：完成率 ≥50% 按完成率线性'
        FROM brands b
        """
    )


def downgrade():
    op.drop_column("salary_records", "kpi_rule_snapshot")
    op.drop_index("ix_kpi_rules_effective_to", table_name="kpi_coefficient_rules")
    op.drop_index("ix_kpi_rules_effective_from", table_name="kpi_coefficient_rules")
    op.drop_index("ix_kpi_rules_brand_id", table_name="kpi_coefficient_rules")
    op.drop_table("kpi_coefficient_rules")
