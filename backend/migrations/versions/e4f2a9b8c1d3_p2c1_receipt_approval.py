"""P2c-1: Receipt 增加审批字段，旧数据视同已确认

Revision ID: e4f2a9b8c1d3
Revises: d8a1b7c3e5f2
Create Date: 2026-04-26

背景（用户 D3 决策）：
- 业务员上传凭证不再直接动账
- 财务在审批中心"确认收款"后才建 fund_flow + 加余额
- 老板问过：一个订单 3 条凭证是一起审（一个不对全部失败）

本 migration 只改 schema：
- receipts 加 status / confirmed_at / confirmed_by / rejected_reason
- 旧 Receipt 全部设 status='confirmed'（不回头审，按 D3 Q3=A）
- 加 index 给 (order_id, status)，查询"订单待审凭证"常用

endpoint 行为改造（不在本 migration）由下一步代码提交。
fund_flows RLS 收紧放到 P2c-3。
"""
from alembic import op
import sqlalchemy as sa


revision = "e4f2a9b8c1d3"
down_revision = "d8a1b7c3e5f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 幂等加字段：用 IF NOT EXISTS 容忍 init_db/create_all 已建出来的情况。
    # 部署流程在某些环境会先 create_all 再 stamp 到旧版，这时字段已存在。
    op.execute(
        "ALTER TABLE receipts "
        "ADD COLUMN IF NOT EXISTS status VARCHAR(30) NOT NULL DEFAULT 'confirmed'"
    )
    op.execute(
        "ALTER TABLE receipts "
        "ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE receipts "
        "ADD COLUMN IF NOT EXISTS confirmed_by VARCHAR(36)"
    )
    op.execute(
        "ALTER TABLE receipts "
        "ADD COLUMN IF NOT EXISTS rejected_reason TEXT"
    )
    # FK 也幂等添加
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        "  WHERE conname = 'fk_receipts_confirmed_by_employee') THEN "
        "ALTER TABLE receipts ADD CONSTRAINT fk_receipts_confirmed_by_employee "
        "FOREIGN KEY (confirmed_by) REFERENCES employees(id); "
        "END IF; "
        "END $$"
    )
    # 旧 Receipt 回填 confirmed_at = created_at（只做一次，近似值）
    op.execute(
        "UPDATE receipts SET confirmed_at = created_at "
        "WHERE status = 'confirmed' AND confirmed_at IS NULL"
    )
    # 拿掉 server_default：以后新建 Receipt 走 ORM default=pending_confirmation
    op.execute("ALTER TABLE receipts ALTER COLUMN status DROP DEFAULT")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_receipts_order_status "
        "ON receipts (order_id, status)"
    )


def downgrade() -> None:
    op.drop_index("ix_receipts_order_status", table_name="receipts")
    op.drop_constraint("fk_receipts_confirmed_by_employee", "receipts", type_="foreignkey")
    op.drop_column("receipts", "rejected_reason")
    op.drop_column("receipts", "confirmed_by")
    op.drop_column("receipts", "confirmed_at")
    op.drop_column("receipts", "status")
