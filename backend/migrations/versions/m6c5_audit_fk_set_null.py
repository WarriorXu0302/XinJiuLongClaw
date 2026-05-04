"""M6c.5: audit_logs 的 actor_id / mall_user_id FK 改为 ON DELETE SET NULL

业务场景：员工离职后其 employees 行可能被清理；mall_user 注销后其行也可能被清理。
审计日志本身的 actor_id 应**保留值不动**（如果 UUID 仍能复活则还能查原人），
但 FK 不能阻塞 employee/mall_user 的删除。

改成 ON DELETE SET NULL 即可：
  - 员工被删 → actor_id 变 NULL；审计日志本体仍在（action/changes/entity_id 等记录完整）
  - mall_user 被删 → mall_user_id 变 NULL

Revision ID: m6c5auditnull
Revises: m6c4kpisnap
Create Date: 2026-05-04
"""
from alembic import op


revision = "m6c5auditnull"
down_revision = "m6c4kpisnap"
branch_labels = None
depends_on = None


def upgrade():
    # actor_id → employees.id
    op.drop_constraint(
        "audit_logs_actor_id_fkey", "audit_logs", type_="foreignkey",
    )
    op.create_foreign_key(
        "audit_logs_actor_id_fkey",
        "audit_logs", "employees",
        ["actor_id"], ["id"],
        ondelete="SET NULL",
    )

    # mall_user_id → mall_users.id
    op.drop_constraint(
        "audit_logs_mall_user_id_fkey", "audit_logs", type_="foreignkey",
    )
    op.create_foreign_key(
        "audit_logs_mall_user_id_fkey",
        "audit_logs", "mall_users",
        ["mall_user_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("audit_logs_actor_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_actor_id_fkey",
        "audit_logs", "employees",
        ["actor_id"], ["id"],
    )
    op.drop_constraint("audit_logs_mall_user_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_mall_user_id_fkey",
        "audit_logs", "mall_users",
        ["mall_user_id"], ["id"],
    )
