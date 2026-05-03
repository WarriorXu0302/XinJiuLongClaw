"""M6a.1: warehouse_transfers + warehouse_transfer_items（跨 ERP/mall 调拨）

业务规则详见 app/models/transfer.py 头部注释。

Revision ID: m6a1whtrans
Revises: m5b1permiso
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa


revision = "m6a1whtrans"
down_revision = "m5b1permiso"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "warehouse_transfers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("transfer_no", sa.String(50), nullable=False, unique=True),
        # 源/目标：side = erp | mall, warehouse_id 按 side 对应表
        sa.Column("source_side", sa.String(10), nullable=False),
        sa.Column("source_warehouse_id", sa.String(36), nullable=False),
        sa.Column("dest_side", sa.String(10), nullable=False),
        sa.Column("dest_warehouse_id", sa.String(36), nullable=False),
        # 状态
        sa.Column(
            "status", sa.String(30),
            nullable=False, server_default="pending_scan",
        ),
        sa.Column(
            "requires_approval", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        # 发起人
        sa.Column(
            "initiator_employee_id", sa.String(36),
            sa.ForeignKey("employees.id"), nullable=False,
        ),
        # 审批
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "approver_employee_id", sa.String(36),
            sa.ForeignKey("employees.id"), nullable=True,
        ),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        # 执行
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        # 业务备注
        sa.Column("reason", sa.Text(), nullable=True),
        # 冗余统计
        sa.Column(
            "total_bottles", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column("total_cost", sa.Numeric(15, 2), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        # CHECK 约束：side 值域 + 源 != 目标
        sa.CheckConstraint(
            "source_side IN ('erp','mall') AND dest_side IN ('erp','mall')",
            name="ck_wh_transfers_side_values",
        ),
        sa.CheckConstraint(
            "NOT (source_side = dest_side AND source_warehouse_id = dest_warehouse_id)",
            name="ck_wh_transfers_src_not_dest",
        ),
    )
    op.create_index("ix_wh_transfers_status", "warehouse_transfers", ["status"])
    op.create_index(
        "ix_wh_transfers_source", "warehouse_transfers",
        ["source_side", "source_warehouse_id"],
    )
    op.create_index(
        "ix_wh_transfers_dest", "warehouse_transfers",
        ["dest_side", "dest_warehouse_id"],
    )
    op.create_index(
        "ix_wh_transfers_created", "warehouse_transfers", ["created_at"],
    )

    op.create_table(
        "warehouse_transfer_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "transfer_id", sa.String(36),
            sa.ForeignKey("warehouse_transfers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("barcode", sa.String(200), nullable=False),
        sa.Column("product_ref", sa.String(36), nullable=False),
        sa.Column("sku_ref", sa.String(36), nullable=True),
        sa.Column("cost_price_snapshot", sa.Numeric(15, 2), nullable=True),
        sa.Column("batch_no_snapshot", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_wh_transfer_items_transfer",
        "warehouse_transfer_items", ["transfer_id"],
    )
    op.create_index(
        "ix_wh_transfer_items_barcode",
        "warehouse_transfer_items", ["barcode"],
    )


def downgrade():
    op.drop_index("ix_wh_transfer_items_barcode", table_name="warehouse_transfer_items")
    op.drop_index("ix_wh_transfer_items_transfer", table_name="warehouse_transfer_items")
    op.drop_table("warehouse_transfer_items")

    op.drop_index("ix_wh_transfers_created", table_name="warehouse_transfers")
    op.drop_index("ix_wh_transfers_dest", table_name="warehouse_transfers")
    op.drop_index("ix_wh_transfers_source", table_name="warehouse_transfers")
    op.drop_index("ix_wh_transfers_status", table_name="warehouse_transfers")
    op.drop_table("warehouse_transfers")
