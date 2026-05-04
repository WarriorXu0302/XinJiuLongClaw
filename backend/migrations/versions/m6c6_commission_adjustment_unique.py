"""M6c.6: commissions.adjustment_source_commission_id 加 partial UNIQUE 索引

G12 数据一致性兜底：即使 approve_return 应用层加了 FOR UPDATE，DB 层多了一道
UNIQUE 保证，防以下场景：
  - 走不同实例的并发（分布式环境各锁各的）
  - 未来漏加锁
  - 直接 INSERT SQL / 脚本误操作

规则：每个源 commission 最多有 1 条对应的 adjustment（is_adjustment=true）。
UNIQUE partial index WHERE is_adjustment = true。

Revision ID: m6c6adjustuniq
Revises: m6c5auditnull
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa


revision = "m6c6adjustuniq"
down_revision = "m6c5auditnull"
branch_labels = None
depends_on = None


def upgrade():
    # PG partial unique index —— 只对 is_adjustment=true 的行生效
    op.create_index(
        "uq_commission_adjustment_source",
        "commissions",
        ["adjustment_source_commission_id"],
        unique=True,
        postgresql_where=sa.text("is_adjustment = true"),
    )


def downgrade():
    op.drop_index("uq_commission_adjustment_source", table_name="commissions")
