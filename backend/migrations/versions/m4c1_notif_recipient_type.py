"""M4c.1: notification_logs 扩展 recipient_type + mall_user_id

Revision ID: m4c1notifmall
Revises: m4a2commissions
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa


revision = "m4c1notifmall"
down_revision = "m4a2commissions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "notification_logs",
        sa.Column("recipient_type", sa.String(20), nullable=False, server_default="erp_user"),
    )
    op.add_column(
        "notification_logs",
        sa.Column(
            "mall_user_id", sa.String(36),
            sa.ForeignKey("mall_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_notif_mall_user_created", "notification_logs",
        ["recipient_type", "mall_user_id", "created_at"],
    )
    op.create_index(
        "ix_notif_status_created", "notification_logs",
        ["status", "created_at"],
    )


def downgrade():
    op.drop_index("ix_notif_status_created", table_name="notification_logs")
    op.drop_index("ix_notif_mall_user_created", table_name="notification_logs")
    op.drop_column("notification_logs", "mall_user_id")
    op.drop_column("notification_logs", "recipient_type")
