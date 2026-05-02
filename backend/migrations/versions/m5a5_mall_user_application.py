"""M5a.5: mall_users 加注册审批字段

Revision ID: m5a5mallapp
Revises: m5a4salarycom
Create Date: 2026-05-03

消费者注册引入审批流程：
  - application_status: pending/approved/rejected（业务员默认 approved 跳过审批）
  - real_name / contact_phone / delivery_address / business_license_url：注册资料
  - rejection_reason / approved_at / approved_by_employee_id：审批记录

测试环境无历史数据迁移负担，默认 default='approved' 保兼容。
"""
from alembic import op
import sqlalchemy as sa


revision = "m5a5mallapp"
down_revision = "m5a4salarycom"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "mall_users",
        sa.Column(
            "application_status", sa.String(20),
            nullable=False, server_default="approved",
        ),
    )
    op.create_index(
        "ix_mall_users_application_status", "mall_users", ["application_status"],
    )
    op.add_column("mall_users", sa.Column("real_name", sa.String(50), nullable=True))
    op.add_column("mall_users", sa.Column("contact_phone", sa.String(20), nullable=True))
    op.add_column("mall_users", sa.Column("delivery_address", sa.Text(), nullable=True))
    op.add_column(
        "mall_users", sa.Column("business_license_url", sa.String(500), nullable=True)
    )
    op.add_column("mall_users", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column(
        "mall_users",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "mall_users",
        sa.Column(
            "approved_by_employee_id", sa.String(36),
            sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True,
        ),
    )


def downgrade():
    op.drop_column("mall_users", "approved_by_employee_id")
    op.drop_column("mall_users", "approved_at")
    op.drop_column("mall_users", "rejection_reason")
    op.drop_column("mall_users", "business_license_url")
    op.drop_column("mall_users", "delivery_address")
    op.drop_column("mall_users", "contact_phone")
    op.drop_column("mall_users", "real_name")
    op.drop_index("ix_mall_users_application_status", table_name="mall_users")
    op.drop_column("mall_users", "application_status")
