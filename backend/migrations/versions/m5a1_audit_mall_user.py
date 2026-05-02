"""M5a.1: audit_logs 扩 mall_user_id（业务员/消费者操作可记审计）

Revision ID: m5a1auditmalluser
Revises: m4b1barcodes
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa


revision = "m5a1auditmalluser"
down_revision = "m4b1barcodes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "audit_logs",
        sa.Column(
            "mall_user_id", sa.String(36),
            sa.ForeignKey("mall_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_audit_logs_mall_user_id",
        "audit_logs", ["mall_user_id"],
    )


def downgrade():
    op.drop_index("ix_audit_logs_mall_user_id", table_name="audit_logs")
    op.drop_column("audit_logs", "mall_user_id")
