"""BACKFILL: 补齐 a1b2c3d4e5f6 原 RLS migration 里 12 张核心表的 policy

Revision ID: a9b8c7d6e5f4
Revises: f1a2b3c4d5e6
Create Date: 2026-04-27

**严重 bug 补救**：

原 migration `a1b2c3d4e5f6_rls_policies` 本来会给 12 张核心表建 RLS
（orders / receipts / payments / expenses / policy_requests / inspection_cases /
 salary_order_links / manufacturer_salary_subsidies / commissions /
 salary_records / accounts / fund_flows）。

但部署流程用的是 `alembic stamp head` 跳过所有 migration 的执行，这些 policy
从未在 DB 里真正生效。所以**自部署以来**：
- 业务员可以看到**所有**订单、收款、账户（包括 master 总资金池）、资金流水
- 跨品牌数据完全不隔离
- 只有 P2a/P2b 手动补的表才有保护

测试发现 salesman 能看到 master 账户金额 → 这个 migration 补齐保护。

本 migration 跟 a1b2c3d4e5f6 的 upgrade 逻辑一致，但用 DROP IF EXISTS + CREATE
保证幂等。
"""
from alembic import op


revision = "a9b8c7d6e5f4"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


BRAND_TABLES = [
    ("orders", "brand_id"),
    ("receipts", "brand_id"),
    ("payments", "brand_id"),
    ("expenses", "brand_id"),
    ("policy_requests", "brand_id"),
    ("inspection_cases", "brand_id"),
    ("salary_order_links", "brand_id"),
    ("manufacturer_salary_subsidies", "brand_id"),
    ("commissions", "brand_id"),
]


def _enable(conn, table):
    conn.exec_driver_sql(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    conn.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _drop(conn, table, *names):
    for n in names:
        conn.exec_driver_sql(f"DROP POLICY IF EXISTS {n} ON {table}")


def upgrade() -> None:
    conn = op.get_bind()

    for table, brand_col in BRAND_TABLES:
        _enable(conn, table)
        _drop(conn, table, "rls_brand_read", "rls_brand_write")
        conn.exec_driver_sql(
            f"CREATE POLICY rls_brand_read ON {table} FOR SELECT "
            f"USING (app_current_is_admin() OR {brand_col}::text = ANY(app_current_brand_ids()))"
        )
        conn.exec_driver_sql(
            f"CREATE POLICY rls_brand_write ON {table} FOR ALL "
            f"USING (app_current_is_admin() OR {brand_col}::text = ANY(app_current_brand_ids())) "
            f"WITH CHECK (app_current_is_admin() OR {brand_col}::text = ANY(app_current_brand_ids()))"
        )

    _enable(conn, "salary_records")
    _drop(conn, "salary_records", "rls_salary_read", "rls_salary_write")
    conn.exec_driver_sql(
        "CREATE POLICY rls_salary_read ON salary_records FOR SELECT USING ("
        " app_current_is_admin() "
        " OR employee_id = app_current_employee_id() "
        " OR EXISTS (SELECT 1 FROM employee_brand_positions ebp "
        "   WHERE ebp.employee_id = salary_records.employee_id "
        "     AND ebp.brand_id::text = ANY(app_current_brand_ids())))"
    )
    conn.exec_driver_sql(
        "CREATE POLICY rls_salary_write ON salary_records FOR ALL "
        "USING (app_current_is_admin()) WITH CHECK (app_current_is_admin())"
    )

    _enable(conn, "accounts")
    _drop(conn, "accounts", "rls_accounts_read", "rls_accounts_write")
    conn.exec_driver_sql(
        "CREATE POLICY rls_accounts_read ON accounts FOR SELECT USING ("
        " app_current_is_admin() "
        " OR (level = 'master' AND app_current_can_see_master()) "
        " OR (level = 'project' AND (brand_id IS NULL OR brand_id::text = ANY(app_current_brand_ids()))))"
    )
    conn.exec_driver_sql(
        "CREATE POLICY rls_accounts_write ON accounts FOR ALL "
        "USING (app_current_is_admin()) WITH CHECK (app_current_is_admin())"
    )

    _enable(conn, "fund_flows")
    _drop(conn, "fund_flows", "rls_fund_flows_read", "rls_fund_flows_write")
    conn.exec_driver_sql(
        "CREATE POLICY rls_fund_flows_read ON fund_flows FOR SELECT USING ("
        " app_current_is_admin() "
        " OR EXISTS (SELECT 1 FROM accounts a WHERE a.id = fund_flows.account_id "
        "   AND ((a.level = 'master' AND app_current_can_see_master()) "
        "     OR (a.level = 'project' AND (a.brand_id IS NULL OR a.brand_id::text = ANY(app_current_brand_ids()))))))"
    )
    # 注：fund_flows 写入策略暂保持 true（P2c-3 会收紧，配合 P2c-1 流程改造）
    conn.exec_driver_sql(
        "CREATE POLICY rls_fund_flows_write ON fund_flows FOR ALL "
        "USING (true) WITH CHECK (true)"
    )


def downgrade() -> None:
    conn = op.get_bind()
    for table, _ in BRAND_TABLES:
        _drop(conn, table, "rls_brand_read", "rls_brand_write")
        conn.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        conn.exec_driver_sql(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    for tbl, prefix in [("salary_records", "rls_salary"), ("accounts", "rls_accounts"), ("fund_flows", "rls_fund_flows")]:
        _drop(conn, tbl, f"{prefix}_read", f"{prefix}_write")
        conn.exec_driver_sql(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY")
        conn.exec_driver_sql(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")
