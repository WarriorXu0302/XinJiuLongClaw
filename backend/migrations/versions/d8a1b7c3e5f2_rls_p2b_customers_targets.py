"""RLS P2b: customers + customer_brand_salesman + sales_targets + policy_claims

Revision ID: d8a1b7c3e5f2
Revises: c7e9f3a1b2d4
Create Date: 2026-04-25

P2a 已处理 8 张表的简单 brand_id 隔离。本 migration 处理 4 张剩余的：

1. customer_brand_salesman (CBS):
   基础关系表。按 brand_id 做品牌隔离（跟普通表一样）。

2. customers:
   客户表本身无 brand_id。通过 EXISTS(CBS) 反查。
   含义：只有 CBS 里存在 "客户 × 我能看的某个品牌" 的绑定，才能看到该客户。
   业务含义："谁绑了这个客户，谁就能看到这个客户"（CLAUDE.md 业务规则）。

3. sales_targets:
   严格品牌隔离：
   - target_level='company': 只 admin 看（全公司目标不跨品牌分享）
   - target_level='brand':   按 brand_id 匹配
   - target_level='employee': 按 brand_id 匹配（员工级目标也标了 brand_id）
   - submitted_by = 自己：任意 status 下能看自己提交的
   - admin: 全放行

4. policy_claims:
   简单 brand_id 匹配（跟 purchase_orders 同款）。
"""
from alembic import op


revision = "d8a1b7c3e5f2"
down_revision = "c7e9f3a1b2d4"
branch_labels = None
depends_on = None


def _enable_and_force(conn, table: str) -> None:
    conn.exec_driver_sql(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    conn.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _drop_policies(conn, table: str, *names: str) -> None:
    for n in names:
        conn.exec_driver_sql(f"DROP POLICY IF EXISTS {n} ON {table}")


def upgrade() -> None:
    conn = op.get_bind()

    # ─── 1. customer_brand_salesman：简单 brand_id 匹配 ──────────────
    _enable_and_force(conn, "customer_brand_salesman")
    _drop_policies(conn, "customer_brand_salesman", "rls_brand_read", "rls_brand_write")
    cbs_expr = (
        "app_current_is_admin() "
        "OR brand_id::text = ANY(app_current_brand_ids())"
    )
    conn.exec_driver_sql(
        f"CREATE POLICY rls_brand_read ON customer_brand_salesman "
        f"FOR SELECT USING ({cbs_expr})"
    )
    conn.exec_driver_sql(
        f"CREATE POLICY rls_brand_write ON customer_brand_salesman "
        f"FOR ALL USING ({cbs_expr}) WITH CHECK ({cbs_expr})"
    )

    # ─── 2. customers：通过 CBS 反查 ─────────────────────────────────
    _enable_and_force(conn, "customers")
    _drop_policies(conn, "customers", "rls_brand_read", "rls_brand_write")
    customers_expr = (
        "app_current_is_admin() "
        "OR EXISTS ("
        "  SELECT 1 FROM customer_brand_salesman cbs "
        "  WHERE cbs.customer_id = customers.id "
        "    AND cbs.brand_id::text = ANY(app_current_brand_ids())"
        ")"
    )
    conn.exec_driver_sql(
        f"CREATE POLICY rls_brand_read ON customers "
        f"FOR SELECT USING ({customers_expr})"
    )
    # 写策略稍宽：admin 或在"我有品牌范围"的情况下都能建新客户
    # （建客户时 CBS 还没有，不能依赖 EXISTS(cbs)——会永远 false）
    customers_write_expr = (
        "app_current_is_admin() "
        "OR array_length(app_current_brand_ids(), 1) > 0"
    )
    conn.exec_driver_sql(
        f"CREATE POLICY rls_brand_write ON customers "
        f"FOR ALL USING ({customers_expr}) "
        f"WITH CHECK ({customers_write_expr})"
    )

    # ─── 3. sales_targets：按品牌/层级隔离 ────────────────────────────
    _enable_and_force(conn, "sales_targets")
    _drop_policies(conn, "sales_targets", "rls_brand_read", "rls_brand_write")
    sales_targets_expr = (
        "app_current_is_admin() "
        "OR submitted_by = app_current_employee_id() "
        # company-level: 只 admin 能看（上面已处理）
        "OR (target_level = 'brand' "
        "    AND brand_id::text = ANY(app_current_brand_ids())) "
        "OR (target_level = 'employee' "
        "    AND (brand_id::text = ANY(app_current_brand_ids()) "
        "         OR employee_id = app_current_employee_id()))"
    )
    conn.exec_driver_sql(
        f"CREATE POLICY rls_brand_read ON sales_targets "
        f"FOR SELECT USING ({sales_targets_expr})"
    )
    # 写策略：admin 或自己提交的
    conn.exec_driver_sql(
        f"CREATE POLICY rls_brand_write ON sales_targets "
        f"FOR ALL USING ({sales_targets_expr}) "
        f"WITH CHECK (app_current_is_admin() OR submitted_by = app_current_employee_id())"
    )

    # ─── 4. policy_claims：简单 brand_id ────────────────────────────
    _enable_and_force(conn, "policy_claims")
    _drop_policies(conn, "policy_claims", "rls_brand_read", "rls_brand_write")
    pc_expr = (
        "app_current_is_admin() "
        "OR brand_id::text = ANY(app_current_brand_ids())"
    )
    conn.exec_driver_sql(
        f"CREATE POLICY rls_brand_read ON policy_claims "
        f"FOR SELECT USING ({pc_expr})"
    )
    conn.exec_driver_sql(
        f"CREATE POLICY rls_brand_write ON policy_claims "
        f"FOR ALL USING ({pc_expr}) WITH CHECK ({pc_expr})"
    )


def downgrade() -> None:
    conn = op.get_bind()
    for table in [
        "customer_brand_salesman",
        "customers",
        "sales_targets",
        "policy_claims",
    ]:
        _drop_policies(conn, table, "rls_brand_read", "rls_brand_write")
        conn.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        conn.exec_driver_sql(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
