"""Bug #3: salary_order_links 加 (order_id, is_manager_share) 唯一约束

Revision ID: b5c8d4e9f2a1
Revises: a9b8c7d6e5f4
Create Date: 2026-04-27

防并发双发提成：两个并发请求同时生成工资单时，_get_fully_paid_orders_for_employee
会把同一订单返回给两个请求。两条 SalaryOrderLink 都能 INSERT，结果同一订单的
提成被分到两份工资单里发了两次。

加 (order_id, is_manager_share) 唯一约束后：第二个请求 INSERT 冲突，ORM 报
IntegrityError，后端兜底（要么整事务回滚重试，要么 ON CONFLICT 跳过）。
约束本身保证数据不错。

"is_manager_share" 区分"员工本人提成"和"经理分成"两种场景——允许一个订单
最多挂两条 link（分别对应员工和经理的工资单）。
"""
from alembic import op


revision = "b5c8d4e9f2a1"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 清理历史重复数据（同 order_id + is_manager_share 只留最早那条）
    op.execute(
        """
        DELETE FROM salary_order_links
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM salary_order_links
            GROUP BY order_id, is_manager_share
        )
        """
    )
    op.execute(
        "ALTER TABLE salary_order_links "
        "ADD CONSTRAINT uq_order_commission_once "
        "UNIQUE (order_id, is_manager_share)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE salary_order_links DROP CONSTRAINT IF EXISTS uq_order_commission_once")
