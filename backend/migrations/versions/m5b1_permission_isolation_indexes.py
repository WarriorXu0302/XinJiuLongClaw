"""M5b.1: 补全权限隔离查询的索引。

本次 P0/P1 gap 修复引入/依赖以下查询，都是"按 actor 过滤"场景，
没索引 → 扫全表 → 随着数据量增长会变慢 + 可能被 attacker 用来做时序侧信道。

新增索引：
  1. `ix_mall_users_linked_employee_unique`
     UNIQUE partial (linked_employee_id) WHERE linked_employee_id IS NOT NULL AND user_type='salesman'
     —— 保证"一个 ERP employee 最多绑一个 mall salesman 账号"在 DB 层强制
     —— 同时支持 rebind-employee 的冲突检查、salesmen 列表 join 两处查询

  2. `ix_mall_barcodes_sku_status_warehouse`
     复合 (sku_id, status, warehouse_id)
     —— ship-mode / ship_order 的 bulk vs scan 路径判别用
     —— 也加速 approve_return 的反向条码查询

  3. `ix_mall_hot_search_active_sort`（已在 m5a9 里建，这里跳过）

  4. `ix_commissions_emp_mall_status`
     复合 (employee_id, mall_order_id, status)
     —— payroll.generate_salary_records 扫业务员的 mall pending commission
     —— 数据多起来后会成热点，之前只有 employee_id (FK, 无独立索引) 和 mall_order_id

Revision ID: m5b1permiso
Revises: m5a9hotsrch
Create Date: 2026-05-03
"""
from alembic import op


revision = "m5b1permiso"
down_revision = "m5a9hotsrch"
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. mall_users.linked_employee_id UNIQUE partial ─────────────────
    # 注：该索引的 UNIQUE 语义也起到"权限完整性约束"作用：
    # 防止两个 mall 账号抢同一个 ERP employee → commission 归属混乱。
    op.create_index(
        "ix_mall_users_linked_employee_unique",
        "mall_users",
        ["linked_employee_id"],
        unique=True,
        postgresql_where="linked_employee_id IS NOT NULL AND user_type = 'salesman'",
    )

    # ── 2. mall_inventory_barcodes (sku_id, status, warehouse_id) ───────
    op.create_index(
        "ix_mall_barcodes_sku_status_wh",
        "mall_inventory_barcodes",
        ["sku_id", "status", "warehouse_id"],
    )

    # ── 3. commissions (employee_id, mall_order_id, status) ─────────────
    # 覆盖 payroll 扫描 + 个人提成明细查询
    op.create_index(
        "ix_commissions_emp_mall_status",
        "commissions",
        ["employee_id", "mall_order_id", "status"],
        postgresql_where="mall_order_id IS NOT NULL",
    )


def downgrade():
    op.drop_index("ix_commissions_emp_mall_status", table_name="commissions")
    op.drop_index("ix_mall_barcodes_sku_status_wh", table_name="mall_inventory_barcodes")
    op.drop_index("ix_mall_users_linked_employee_unique", table_name="mall_users")
