"""M6b.1: 门店零售（收银系统）

- products 加 min_sale_price / max_sale_price（零售售价区间）
- employees 加 assigned_store_id（店员归属门店仓）
- mall_users 加 assigned_store_id（收银入口可见性判定）
- 新表 store_sales / store_sale_items / retail_commission_rates

业务规则见 app/models/store_sale.py 头部。

Revision ID: m6b1storsal
Revises: m6a1whtrans
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa


revision = "m6b1storsal"
down_revision = "m6a1whtrans"
branch_labels = None
depends_on = None


def upgrade():
    # 0. commissions 加 store_sale_id（门店零售提成挂靠；和 mall_order_id/order_id 三者互斥）
    op.add_column(
        "commissions",
        sa.Column("store_sale_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_commissions_store_sale", "commissions", ["store_sale_id"],
        postgresql_where=sa.text("store_sale_id IS NOT NULL"),
    )
    # 注：FK 在 store_sales 表建完后再加，见步骤 4 之后补

    # 1. products：售价区间
    op.add_column("products", sa.Column("min_sale_price", sa.Numeric(15, 2), nullable=True))
    op.add_column("products", sa.Column("max_sale_price", sa.Numeric(15, 2), nullable=True))

    # 2. employees：店员所属门店仓
    op.add_column(
        "employees",
        sa.Column("assigned_store_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_employees_assigned_store",
        "employees", "warehouses",
        ["assigned_store_id"], ["id"],
    )

    # 3. mall_users：同步店员归属（小程序端收银入口判定用）
    op.add_column(
        "mall_users",
        sa.Column("assigned_store_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_mall_users_assigned_store",
        "mall_users", "warehouses",
        ["assigned_store_id"], ["id"],
    )

    # 4. store_sales：销售单头
    op.create_table(
        "store_sales",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sale_no", sa.String(50), nullable=False, unique=True),
        sa.Column(
            "store_id", sa.String(36),
            sa.ForeignKey("warehouses.id"), nullable=False,
        ),
        sa.Column(
            "cashier_employee_id", sa.String(36),
            sa.ForeignKey("employees.id"), nullable=False,
        ),
        sa.Column(
            "customer_id", sa.String(36),
            sa.ForeignKey("mall_users.id"), nullable=False,
        ),
        sa.Column("total_sale_amount", sa.Numeric(15, 2),
                  nullable=False, server_default="0"),
        sa.Column("total_cost", sa.Numeric(15, 2),
                  nullable=False, server_default="0"),
        sa.Column("total_profit", sa.Numeric(15, 2),
                  nullable=False, server_default="0"),
        sa.Column("total_commission", sa.Numeric(15, 2),
                  nullable=False, server_default="0"),
        sa.Column("total_bottles", sa.Integer(),
                  nullable=False, server_default="0"),
        sa.Column("payment_method", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20),
                  nullable=False, server_default="completed"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "payment_method IN ('cash','wechat','alipay','card')",
            name="ck_store_sales_payment_method",
        ),
    )
    op.create_index("ix_store_sales_store", "store_sales", ["store_id"])
    op.create_index("ix_store_sales_cashier", "store_sales", ["cashier_employee_id"])
    op.create_index("ix_store_sales_customer", "store_sales", ["customer_id"])
    op.create_index("ix_store_sales_created", "store_sales", ["created_at"])

    # 补 commissions.store_sale_id 的 FK（依赖 store_sales 已建）
    op.create_foreign_key(
        "fk_commissions_store_sale",
        "commissions", "store_sales",
        ["store_sale_id"], ["id"],
    )

    # 5. store_sale_items：每瓶一行
    op.create_table(
        "store_sale_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "sale_id", sa.String(36),
            sa.ForeignKey("store_sales.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("barcode", sa.String(200), nullable=False),
        sa.Column(
            "product_id", sa.String(36),
            sa.ForeignKey("products.id"), nullable=False,
        ),
        sa.Column("batch_no_snapshot", sa.String(100), nullable=True),
        sa.Column("sale_price", sa.Numeric(15, 2), nullable=False),
        sa.Column("cost_price_snapshot", sa.Numeric(15, 2), nullable=False),
        sa.Column("profit", sa.Numeric(15, 2), nullable=False),
        sa.Column("rate_on_profit_snapshot", sa.Numeric(7, 4), nullable=True),
        sa.Column("commission_amount", sa.Numeric(15, 2),
                  nullable=False, server_default="0"),
        sa.Column(
            "commission_id", sa.String(36),
            sa.ForeignKey("commissions.id"), nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_store_sale_items_sale", "store_sale_items", ["sale_id"])
    op.create_index("ix_store_sale_items_barcode", "store_sale_items", ["barcode"])
    op.create_index("ix_store_sale_items_product", "store_sale_items", ["product_id"])

    # 6. retail_commission_rates：每员工每商品一个利润提成率
    op.create_table(
        "retail_commission_rates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "employee_id", sa.String(36),
            sa.ForeignKey("employees.id"), nullable=False,
        ),
        sa.Column(
            "product_id", sa.String(36),
            sa.ForeignKey("products.id"), nullable=False,
        ),
        sa.Column("rate_on_profit", sa.Numeric(7, 4), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("employee_id", "product_id",
                            name="uq_retail_commission_emp_product"),
    )
    op.create_index(
        "ix_retail_commission_employee",
        "retail_commission_rates", ["employee_id"],
    )


def downgrade():
    op.drop_index("ix_retail_commission_employee", table_name="retail_commission_rates")
    op.drop_table("retail_commission_rates")

    op.drop_index("ix_store_sale_items_product", table_name="store_sale_items")
    op.drop_index("ix_store_sale_items_barcode", table_name="store_sale_items")
    op.drop_index("ix_store_sale_items_sale", table_name="store_sale_items")
    op.drop_table("store_sale_items")

    op.drop_constraint("fk_commissions_store_sale", "commissions", type_="foreignkey")
    op.drop_index("ix_store_sales_created", table_name="store_sales")
    op.drop_index("ix_store_sales_customer", table_name="store_sales")
    op.drop_index("ix_store_sales_cashier", table_name="store_sales")
    op.drop_index("ix_store_sales_store", table_name="store_sales")
    op.drop_table("store_sales")

    op.drop_constraint("fk_mall_users_assigned_store", "mall_users", type_="foreignkey")
    op.drop_column("mall_users", "assigned_store_id")

    op.drop_constraint("fk_employees_assigned_store", "employees", type_="foreignkey")
    op.drop_column("employees", "assigned_store_id")

    op.drop_column("products", "max_sale_price")
    op.drop_column("products", "min_sale_price")

    op.drop_index("ix_commissions_store_sale", table_name="commissions")
    op.drop_column("commissions", "store_sale_id")
