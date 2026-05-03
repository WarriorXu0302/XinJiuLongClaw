"""M5a.7: mall_job_logs 表（定时任务执行历史）

Revision ID: m5a7joblog
Revises: m5a6purchwh
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa


revision = "m5a7joblog"
down_revision = "m5a6purchwh"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mall_job_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("job_name", sa.String(100), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False, server_default="scheduler"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_mall_job_logs_name_started", "mall_job_logs",
        ["job_name", "started_at"],
    )
    op.create_index(
        "ix_mall_job_logs_started", "mall_job_logs", ["started_at"],
    )


def downgrade():
    op.drop_index("ix_mall_job_logs_started", table_name="mall_job_logs")
    op.drop_index("ix_mall_job_logs_name_started", table_name="mall_job_logs")
    op.drop_table("mall_job_logs")
