"""mall M4a: 履约域（payments / shipments / attachments / skip_logs / skip_alerts）

Revision ID: m4a1fulfilment
Revises: m3a1mallorders
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "m4a1fulfilment"
down_revision = "m3a1mallorders"
branch_labels = None
depends_on = None


def upgrade():
    # =========================================================================
    # mall_payments
    # =========================================================================
    op.create_table(
        "mall_payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(36),
                  sa.ForeignKey("mall_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_by_user_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("payment_method", sa.String(20), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False, server_default="offline"),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending_confirmation"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by_employee_id", sa.String(36),
                  sa.ForeignKey("employees.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("rejected_reason", sa.Text, nullable=True),
        sa.Column("remarks", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mall_payments_order_status", "mall_payments", ["order_id", "status"])
    op.create_index("ix_mall_payments_status_created", "mall_payments", ["status", "created_at"])

    # =========================================================================
    # mall_shipments
    # =========================================================================
    op.create_table(
        "mall_shipments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(36),
                  sa.ForeignKey("mall_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("carrier_name", sa.String(100), nullable=True),
        sa.Column("tracking_no", sa.String(100), nullable=True),
        sa.Column("warehouse_id", sa.String(36),
                  sa.ForeignKey("mall_warehouses.id"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tracks", postgresql.JSONB, nullable=True),
        sa.Column("tracks_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mall_shipments_order", "mall_shipments", ["order_id"], unique=True)

    # =========================================================================
    # mall_attachments
    # =========================================================================
    op.create_table(
        "mall_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("ref_type", sa.String(30), nullable=False),
        sa.Column("ref_id", sa.String(36), nullable=False),
        sa.Column("file_url", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("uploaded_by_user_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("client_ip", sa.String(45), nullable=True),
        sa.Column("uploaded_user_agent", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mall_attachments_ref", "mall_attachments", ["ref_type", "ref_id"])
    op.create_index("ix_mall_attachments_kind_created", "mall_attachments", ["kind", "created_at"])

    # =========================================================================
    # mall_customer_skip_logs
    # =========================================================================
    op.create_table(
        "mall_customer_skip_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_user_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("salesman_user_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("order_id", sa.String(36),
                  sa.ForeignKey("mall_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skip_type", sa.String(30), nullable=False),
        sa.Column("dismissed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_mall_skip_logs_pair_created", "mall_customer_skip_logs",
        ["customer_user_id", "salesman_user_id", "created_at"],
    )
    op.create_index("ix_mall_skip_logs_order", "mall_customer_skip_logs", ["order_id"])

    # =========================================================================
    # mall_skip_alerts
    # =========================================================================
    op.create_table(
        "mall_skip_alerts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_user_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("salesman_user_id", sa.String(36),
                  sa.ForeignKey("mall_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("skip_count", sa.Integer, nullable=False),
        sa.Column("trigger_log_ids", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("resolved_by_user_id", sa.String(36), nullable=True),
        sa.Column("resolved_by_type", sa.String(20), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text, nullable=True),
        sa.Column("appeal_reason", sa.Text, nullable=True),
        sa.Column("appeal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mall_skip_alerts_salesman_status", "mall_skip_alerts", ["salesman_user_id", "status"])
    op.create_index("ix_mall_skip_alerts_customer_status", "mall_skip_alerts", ["customer_user_id", "status"])
    # 同一 (customer, salesman) 至多一条 open（partial unique index，并发挡重）
    op.create_index(
        "uq_mall_skip_alerts_pair_open", "mall_skip_alerts",
        ["customer_user_id", "salesman_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade():
    op.drop_index("uq_mall_skip_alerts_pair_open", table_name="mall_skip_alerts")
    for ix in ["ix_mall_skip_alerts_customer_status", "ix_mall_skip_alerts_salesman_status"]:
        op.drop_index(ix, table_name="mall_skip_alerts")
    op.drop_table("mall_skip_alerts")

    for ix in ["ix_mall_skip_logs_order", "ix_mall_skip_logs_pair_created"]:
        op.drop_index(ix, table_name="mall_customer_skip_logs")
    op.drop_table("mall_customer_skip_logs")

    for ix in ["ix_mall_attachments_kind_created", "ix_mall_attachments_ref"]:
        op.drop_index(ix, table_name="mall_attachments")
    op.drop_table("mall_attachments")

    op.drop_index("ix_mall_shipments_order", table_name="mall_shipments")
    op.drop_table("mall_shipments")

    for ix in ["ix_mall_payments_status_created", "ix_mall_payments_order_status"]:
        op.drop_index(ix, table_name="mall_payments")
    op.drop_table("mall_payments")
