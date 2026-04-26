"""FIX: created_at default 改成真正的 NOW() 函数

Revision ID: f1a2b3c4d5e6
Revises: e4f2a9b8c1d3
Create Date: 2026-04-26

背景（严重 bug）：
ORM 模型用的是 `server_default="now()"`（字符串字面量），SQLAlchemy 把它当 PG
字面量 `'now()'::timestamp` 传给建表语句。PG 建表时**立即求值**这个字面量，
结果 default 被固化成"建表那一刻"的时间。

症状：所有表的 created_at 默认值**都是同一个静态时间**（表创建时间），
新插入的行如果没显式传 created_at，就都被标记成那个时间——导致：
- 订单列表里所有订单"创建时间"相同
- 审计日志时间戳没意义
- 考勤记录时间全错
- 任何用 created_at 排序/筛选/归档的业务都会炸

修法：
- 模型层改成 `server_default=func.now()` （真正的 PG 函数引用）
- 本 migration 用 ALTER COLUMN SET DEFAULT now() 修所有表的 DB default
- 已有的静态 default 值会被覆盖

对已有行的影响：
本 migration 只改 default。已插入的行（created_at 已固化为静态值）**不回溯修复**——
因为没法知道每行真实创建时间。如果本地开发数据，建议清库重来更干净。
"""
from alembic import op


revision = "f1a2b3c4d5e6"
down_revision = "e4f2a9b8c1d3"
branch_labels = None
depends_on = None


# 所有带 created_at 的表（grep 模型得到）
TABLES_WITH_CREATED_AT = [
    "accounts", "assessment_items", "attendance_rules", "audit_logs",
    "bottle_destructions", "brand_salary_schemes", "brands", "checkin_records",
    "claim_settlement_links", "commissions", "customer_brand_salesman",
    "customer_visits", "customers", "employee_brand_positions", "employees",
    "expense_categories", "expense_claims", "expenses", "feishu_bindings",
    "financing_orders", "financing_repayments", "fund_flows", "inspection_cases",
    "inventory", "inventory_barcodes", "kpis", "leave_requests",
    "manufacturer_external_identities", "manufacturer_salary_subsidies",
    "manufacturer_settlements", "market_cleanup_cases", "notification_logs",
    "order_items", "orders", "payment_requests", "payments", "policy_adjustments",
    "policy_claim_items", "policy_claims", "policy_item_expenses",
    "policy_request_items", "policy_requests", "policy_template_benefits",
    "policy_templates", "policy_usage_records", "positions", "products",
    "purchase_order_items",
    "purchase_orders", "receipts", "receivables", "roles",
    "salary_order_links", "salary_records", "sales_targets", "stock_flow",
    "stock_out_allocations", "suppliers", "tasting_wine_usage", "user_roles",
    "users", "warehouses",
]


def upgrade() -> None:
    conn = op.get_bind()
    for table in TABLES_WITH_CREATED_AT:
        # 检查表和列是否存在（防止删过的表失败）
        exists = conn.exec_driver_sql(
            "SELECT 1 FROM information_schema.columns "
            f"WHERE table_name='{table}' AND column_name='created_at'"
        ).scalar()
        if exists:
            conn.exec_driver_sql(
                f"ALTER TABLE {table} ALTER COLUMN created_at SET DEFAULT now()"
            )


def downgrade() -> None:
    # 不能真 downgrade（回到静态 default 是回到 bug 状态）。仅把 default 去掉。
    conn = op.get_bind()
    for table in TABLES_WITH_CREATED_AT:
        exists = conn.exec_driver_sql(
            "SELECT 1 FROM information_schema.columns "
            f"WHERE table_name='{table}' AND column_name='created_at'"
        ).scalar()
        if exists:
            conn.exec_driver_sql(
                f"ALTER TABLE {table} ALTER COLUMN created_at DROP DEFAULT"
            )
