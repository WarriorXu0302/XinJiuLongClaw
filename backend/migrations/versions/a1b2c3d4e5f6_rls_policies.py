"""RLS policies for multi-brand isolation

Revision ID: a1b2c3d4e5f6
Revises: bdc93adb3498
Create Date: 2026-04-19

建立两个 DB role:
  erp_app   —— 应用连接用（NOBYPASSRLS）。受 RLS 策略约束
  erpuser   —— 继续作为超级用户，跑 alembic / 后台 job，不受 RLS 影响

对敏感表开启 RLS + 品牌隔离策略。session 上下文由 FastAPI get_db 在事务开始时
SET LOCAL 写入（app.brand_ids / app.is_admin / app.can_see_master / app.employee_id）。

策略核心：
  is_admin 为 true → 放行全部
  brand_id IN brand_ids（string_to_array 解析）→ 放行
  accounts.level='master' → 仅 can_see_master
"""
from alembic import op


# revision identifiers
revision = 'a1b2c3d4e5f6'
down_revision = 'bdc93adb3498'
branch_labels = None
depends_on = None


# 受 RLS 保护的表（按品牌过滤）
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


# 辅助函数：当前 JWT 上下文（逐条执行，asyncpg 不允许多 statement）
HELPER_FNS = [
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
]

DROP_HELPER_FNS = [
    "DROP FUNCTION IF EXISTS app_current_is_admin()",
    "DROP FUNCTION IF EXISTS app_current_can_see_master()",
    "DROP FUNCTION IF EXISTS app_current_brand_ids()",
    "DROP FUNCTION IF EXISTS app_current_employee_id()",
]


def upgrade() -> None:
    conn = op.get_bind()

    # 1. 建 app role（如已存在则跳过）
    conn.exec_driver_sql(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='erp_app') THEN "
        "CREATE ROLE erp_app LOGIN PASSWORD 'erp_app_pw' NOBYPASSRLS; "
        "END IF; "
        "END $$"
    )

    # 2. 授权 erp_app 访问当前库 + schema 内所有表（含未来新建的）
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

    # 3. 建 helper 函数
    for fn_sql in HELPER_FNS:
        conn.exec_driver_sql(fn_sql)

    # 4. 品牌隔离表：启用 RLS + 通用策略
    for table, brand_col in BRAND_TABLES:
        conn.exec_driver_sql(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        conn.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        conn.exec_driver_sql(
            f"CREATE POLICY rls_brand_read ON {table} FOR SELECT "
            f"USING (app_current_is_admin() OR {brand_col}::text = ANY(app_current_brand_ids()))"
        )
        conn.exec_driver_sql(
            f"CREATE POLICY rls_brand_write ON {table} FOR ALL "
            f"USING (app_current_is_admin() OR {brand_col}::text = ANY(app_current_brand_ids())) "
            f"WITH CHECK (app_current_is_admin() OR {brand_col}::text = ANY(app_current_brand_ids()))"
        )

    # 5. salary_records 按员工主属品牌过滤
    conn.exec_driver_sql("ALTER TABLE salary_records ENABLE ROW LEVEL SECURITY")
    conn.exec_driver_sql("ALTER TABLE salary_records FORCE ROW LEVEL SECURITY")
    conn.exec_driver_sql(
        "CREATE POLICY rls_salary_read ON salary_records FOR SELECT "
        "USING ("
        " app_current_is_admin() "
        " OR employee_id = app_current_employee_id() "
        " OR EXISTS (SELECT 1 FROM employee_brand_positions ebp "
        "   WHERE ebp.employee_id = salary_records.employee_id "
        "     AND ebp.brand_id::text = ANY(app_current_brand_ids())) "
        ")"
    )
    conn.exec_driver_sql(
        "CREATE POLICY rls_salary_write ON salary_records FOR ALL "
        "USING (app_current_is_admin()) WITH CHECK (app_current_is_admin())"
    )

    # 6. accounts：master 只对 can_see_master 可见；project 按 brand_ids
    conn.exec_driver_sql("ALTER TABLE accounts ENABLE ROW LEVEL SECURITY")
    conn.exec_driver_sql("ALTER TABLE accounts FORCE ROW LEVEL SECURITY")
    conn.exec_driver_sql(
        "CREATE POLICY rls_accounts_read ON accounts FOR SELECT "
        "USING ("
        " app_current_is_admin() "
        " OR (level = 'master' AND app_current_can_see_master()) "
        " OR (level = 'project' AND (brand_id IS NULL OR brand_id::text = ANY(app_current_brand_ids()))) "
        ")"
    )
    conn.exec_driver_sql(
        "CREATE POLICY rls_accounts_write ON accounts FOR ALL "
        "USING (app_current_is_admin()) WITH CHECK (app_current_is_admin())"
    )

    # 7. fund_flows：按 account_id 的可见性反查
    conn.exec_driver_sql("ALTER TABLE fund_flows ENABLE ROW LEVEL SECURITY")
    conn.exec_driver_sql("ALTER TABLE fund_flows FORCE ROW LEVEL SECURITY")
    conn.exec_driver_sql(
        "CREATE POLICY rls_fund_flows_read ON fund_flows FOR SELECT "
        "USING ("
        " app_current_is_admin() "
        " OR EXISTS (SELECT 1 FROM accounts a WHERE a.id = fund_flows.account_id "
        "   AND ((a.level = 'master' AND app_current_can_see_master()) "
        "     OR (a.level = 'project' AND (a.brand_id IS NULL OR a.brand_id::text = ANY(app_current_brand_ids()))))) "
        ")"
    )
    conn.exec_driver_sql(
        "CREATE POLICY rls_fund_flows_write ON fund_flows FOR ALL "
        "USING (true) WITH CHECK (true)"
    )


def downgrade() -> None:
    conn = op.get_bind()

    for table, _ in BRAND_TABLES:
        conn.exec_driver_sql(f"DROP POLICY IF EXISTS rls_brand_read ON {table}")
        conn.exec_driver_sql(f"DROP POLICY IF EXISTS rls_brand_write ON {table}")
        conn.exec_driver_sql(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        conn.exec_driver_sql(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")

    for tbl, prefix in [("salary_records", "rls_salary"), ("accounts", "rls_accounts"), ("fund_flows", "rls_fund_flows")]:
        conn.exec_driver_sql(f"DROP POLICY IF EXISTS {prefix}_read ON {tbl}")
        conn.exec_driver_sql(f"DROP POLICY IF EXISTS {prefix}_write ON {tbl}")
        conn.exec_driver_sql(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")
        conn.exec_driver_sql(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY")

    for drop_sql in DROP_HELPER_FNS:
        conn.exec_driver_sql(drop_sql)
