"""RLS P2a: 给 8 张带 brand_id 的表补 RLS policy

Revision ID: c7e9f3a1b2d4
Revises: f17a_feishu_binding
Create Date: 2026-04-25

原因：
- health-check 报告发现 11 张带 brand_id 但没 RLS 的表
- 本 migration 处理 8 张直接/间接 brand_id 隔离的表
- customers / sales_targets / policy_claims 策略复杂，由后续 P2b 处理

策略：
- 直接 brand_id 的 7 张表：admin 或 brand_id 匹配
- policy_templates / brand_salary_schemes：另外放行 brand_id IS NULL（通用模板）
- policy_usage_records / tasting_wine_usage：通过关联表反查 brand_id

写入（WITH CHECK）：同读取。admin 或 brand_id 匹配。

幂等保证：
- 所有 policy 用 DROP IF EXISTS + CREATE，可重复执行
- 先幂等重建 erp_app role + helper functions（避免遗忘 a1b2c3d4e5f6 pre-req）
"""
from alembic import op


revision = "c7e9f3a1b2d4"
down_revision = "f17a_feishu_binding"
branch_labels = None
depends_on = None


# ─── 1. 简单 brand_id 隔离的表 ────────────────────────────────
# (表名, brand_id 列名, 是否允许 NULL 对所有人可见)
SIMPLE_TABLES = [
    ("purchase_orders",     "brand_id", False),
    ("financing_orders",    "brand_id", False),
    ("expense_claims",      "brand_id", False),
    ("receivables",         "brand_id", False),
    ("policy_templates",    "brand_id", True),   # NULL = 通用模板全员可见
    ("brand_salary_schemes","brand_id", True),   # NULL = 公司通用薪酬
]


# ─── 2. 通过关联表反查的表 ────────────────────────────────────
# tasting_wine_usage 多了一层，单独处理
JOIN_POLICIES = {
    # policy_usage_records → policy_requests.brand_id
    "policy_usage_records": {
        "read": (
            "app_current_is_admin() "
            "OR EXISTS (SELECT 1 FROM policy_requests pr "
            "           WHERE pr.id = policy_usage_records.policy_request_id "
            "             AND pr.brand_id::text = ANY(app_current_brand_ids()))"
        ),
        "write": (
            "app_current_is_admin() "
            "OR EXISTS (SELECT 1 FROM policy_requests pr "
            "           WHERE pr.id = policy_usage_records.policy_request_id "
            "             AND pr.brand_id::text = ANY(app_current_brand_ids()))"
        ),
    },
    # tasting_wine_usage → policy_usage_records → policy_requests.brand_id
    "tasting_wine_usage": {
        "read": (
            "app_current_is_admin() "
            "OR EXISTS (SELECT 1 FROM policy_usage_records pur "
            "           JOIN policy_requests pr ON pr.id = pur.policy_request_id "
            "           WHERE pur.id = tasting_wine_usage.source_usage_record_id "
            "             AND pr.brand_id::text = ANY(app_current_brand_ids()))"
        ),
        "write": (
            "app_current_is_admin() "
            "OR EXISTS (SELECT 1 FROM policy_usage_records pur "
            "           JOIN policy_requests pr ON pr.id = pur.policy_request_id "
            "           WHERE pur.id = tasting_wine_usage.source_usage_record_id "
            "             AND pr.brand_id::text = ANY(app_current_brand_ids()))"
        ),
    },
}


def _enable_and_force(conn, table: str) -> None:
    conn.exec_driver_sql(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    conn.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _drop_and_create_simple(conn, table: str, brand_col: str, allow_null: bool) -> None:
    """幂等：先 drop 再建。NULL 放行对 policy_templates / brand_salary_schemes 适用。"""
    conn.exec_driver_sql(f"DROP POLICY IF EXISTS rls_brand_read ON {table}")
    conn.exec_driver_sql(f"DROP POLICY IF EXISTS rls_brand_write ON {table}")

    null_clause = f" OR {brand_col} IS NULL" if allow_null else ""
    using_expr = (
        f"app_current_is_admin() "
        f"OR {brand_col}::text = ANY(app_current_brand_ids()){null_clause}"
    )

    conn.exec_driver_sql(
        f"CREATE POLICY rls_brand_read ON {table} FOR SELECT USING ({using_expr})"
    )
    conn.exec_driver_sql(
        f"CREATE POLICY rls_brand_write ON {table} FOR ALL "
        f"USING ({using_expr}) WITH CHECK ({using_expr})"
    )


def _drop_and_create_join(conn, table: str, spec: dict) -> None:
    conn.exec_driver_sql(f"DROP POLICY IF EXISTS rls_brand_read ON {table}")
    conn.exec_driver_sql(f"DROP POLICY IF EXISTS rls_brand_write ON {table}")
    conn.exec_driver_sql(
        f"CREATE POLICY rls_brand_read ON {table} FOR SELECT USING ({spec['read']})"
    )
    conn.exec_driver_sql(
        f"CREATE POLICY rls_brand_write ON {table} FOR ALL "
        f"USING ({spec['write']}) WITH CHECK ({spec['write']})"
    )


def _ensure_rls_prerequisites(conn) -> None:
    """幂等建 erp_app role + helper functions + GRANTs。

    这些本该由 a1b2c3d4e5f6_rls_policies 建；但如果 stamp 跳过了那个 migration
    （参见部署流程），这里兜底保证本 migration 能独立跑上去。
    """
    # 1. erp_app role
    conn.exec_driver_sql(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='erp_app') THEN "
        "CREATE ROLE erp_app LOGIN PASSWORD 'erp_app_pw' NOBYPASSRLS; "
        "END IF; "
        "END $$"
    )
    # 2. GRANT（CURRENT_DATABASE 避免写死 newerp）
    conn.exec_driver_sql("GRANT CONNECT ON DATABASE newerp TO erp_app")
    conn.exec_driver_sql("GRANT USAGE ON SCHEMA public TO erp_app")
    conn.exec_driver_sql("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO erp_app")
    conn.exec_driver_sql("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO erp_app")
    conn.exec_driver_sql(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO erp_app"
    )
    conn.exec_driver_sql(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO erp_app"
    )
    # 3. helper functions (CREATE OR REPLACE 幂等)
    for fn_sql in [
        """CREATE OR REPLACE FUNCTION app_current_is_admin() RETURNS boolean
           LANGUAGE sql STABLE AS $$
           SELECT COALESCE(current_setting('app.is_admin', true)::boolean, false)
           $$""",
        """CREATE OR REPLACE FUNCTION app_current_can_see_master() RETURNS boolean
           LANGUAGE sql STABLE AS $$
           SELECT COALESCE(current_setting('app.can_see_master', true)::boolean, false)
           $$""",
        """CREATE OR REPLACE FUNCTION app_current_brand_ids() RETURNS text[]
           LANGUAGE sql STABLE AS $$
           SELECT CASE
             WHEN COALESCE(current_setting('app.brand_ids', true), '') = '' THEN ARRAY[]::text[]
             ELSE string_to_array(current_setting('app.brand_ids', true), ',')
           END
           $$""",
        """CREATE OR REPLACE FUNCTION app_current_employee_id() RETURNS text
           LANGUAGE sql STABLE AS $$
           SELECT NULLIF(COALESCE(current_setting('app.employee_id', true), ''), '')
           $$""",
    ]:
        conn.exec_driver_sql(fn_sql)


def upgrade() -> None:
    conn = op.get_bind()

    _ensure_rls_prerequisites(conn)

    for table, brand_col, allow_null in SIMPLE_TABLES:
        _enable_and_force(conn, table)
        _drop_and_create_simple(conn, table, brand_col, allow_null)

    for table, spec in JOIN_POLICIES.items():
        _enable_and_force(conn, table)
        _drop_and_create_join(conn, table, spec)


def downgrade() -> None:
    conn = op.get_bind()

    for table, _, _ in SIMPLE_TABLES:
        conn.exec_driver_sql(f"DROP POLICY IF EXISTS rls_brand_read ON {table}")
        conn.exec_driver_sql(f"DROP POLICY IF EXISTS rls_brand_write ON {table}")
        conn.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        conn.exec_driver_sql(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    for table in JOIN_POLICIES:
        conn.exec_driver_sql(f"DROP POLICY IF EXISTS rls_brand_read ON {table}")
        conn.exec_driver_sql(f"DROP POLICY IF EXISTS rls_brand_write ON {table}")
        conn.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        conn.exec_driver_sql(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
