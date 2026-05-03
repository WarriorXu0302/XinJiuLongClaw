"""M5a.8: mall_return_requests（C 端退货申请）

Revision ID: m5a8return
Revises: m5a7joblog
Create Date: 2026-05-03

业务：
  - 消费者对 completed / partial_closed 订单可申请退货
  - 财务 approved 后退库存 + 订单→refunded
  - refunded 时记 refunded_at 完成全流程
"""
from alembic import op
import sqlalchemy as sa


revision = "m5a8return"
down_revision = "m5a7joblog"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mall_return_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "order_id", sa.String(36),
            sa.ForeignKey("mall_orders.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(20),
            nullable=False, server_default="pending",
        ),
        sa.Column(
            "reviewer_employee_id", sa.String(36),
            sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("refund_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refund_method", sa.String(20), nullable=True),
        sa.Column("refund_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_mall_return_requests_order", "mall_return_requests", ["order_id"],
    )
    op.create_index(
        "ix_mall_return_requests_user", "mall_return_requests", ["user_id"],
    )
    op.create_index(
        "ix_mall_return_requests_status", "mall_return_requests", ["status"],
    )
    # 一个订单最多一条活跃退货申请（pending / approved）
    op.create_index(
        "uq_mall_return_active_per_order", "mall_return_requests",
        ["order_id"], unique=True,
        postgresql_where=sa.text("status IN ('pending', 'approved')"),
    )


def downgrade():
    op.drop_index("uq_mall_return_active_per_order", table_name="mall_return_requests")
    op.drop_index("ix_mall_return_requests_status", table_name="mall_return_requests")
    op.drop_index("ix_mall_return_requests_user", table_name="mall_return_requests")
    op.drop_index("ix_mall_return_requests_order", table_name="mall_return_requests")
    op.drop_table("mall_return_requests")
