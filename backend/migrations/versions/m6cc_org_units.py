"""M6c.c: 建 org_units 经营单元表 + 给 5 张汇总表加 org_unit_id

背景：
  - 现有系统主轴是 brand（品牌事业部独立核算），零售门店/批发商城被边缘化
  - 老板要看全局时只能按品牌看，看不到"品牌代理 / 零售 / 商城"三大事业视角
  - 这个 migration 只加分析维度，不动 brand_id 主轴、不动 RLS、不动账务

本 migration 改动：
  1) 新建 org_units 表 + 种子 3 条（brand_agent / retail / mall）
  2) 给 orders / commissions / store_sales / mall_orders / mall_purchase_orders
     加 org_unit_id FK（先 NULL → 回填 → SET NOT NULL）
  3) commissions 按 mall_order_id IS NOT NULL 回填 mall；其余全 brand_agent
  4) mall_purchase_orders 按 scope 回填（mall→mall, store→retail）

Revision ID: m6ccorgunits
Revises: 7da04a1ce06a
Create Date: 2026-05-07
"""
from alembic import op
import sqlalchemy as sa


revision = "m6ccorgunits"
down_revision = "7da04a1ce06a"
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # 1. org_units 主表
    # ------------------------------------------------------------------
    op.create_table(
        "org_units",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("code", name="uq_org_units_code"),
    )

    # 种子 3 条
    op.execute("""
        INSERT INTO org_units (id, code, name, sort_order, is_active) VALUES
          (gen_random_uuid()::text, 'brand_agent', '品牌代理事业部', 1, true),
          (gen_random_uuid()::text, 'retail',      '零售事业部',     2, true),
          (gen_random_uuid()::text, 'mall',        '批发商城事业部', 3, true)
        ON CONFLICT (code) DO NOTHING;
    """)

    # ------------------------------------------------------------------
    # 2. 5 张业务表加 org_unit_id（先 NULL → 回填 → SET NOT NULL）
    #    所有表共用一个回填 CTE 取 id
    # ------------------------------------------------------------------
    for table_name in ("orders", "commissions", "store_sales", "mall_orders", "mall_purchase_orders"):
        op.add_column(
            table_name,
            sa.Column(
                "org_unit_id", sa.String(36),
                sa.ForeignKey("org_units.id", name=f"fk_{table_name}_org_unit"),
                nullable=True,  # 暂时允许 NULL，回填后再 SET NOT NULL
            ),
        )

    # ------------------------------------------------------------------
    # 3. 回填
    # ------------------------------------------------------------------
    # 默认全部归 brand_agent
    for t in ("orders", "commissions", "store_sales"):
        op.execute(f"""
            UPDATE {t} SET org_unit_id = (
                SELECT id FROM org_units WHERE code = '{'retail' if t == 'store_sales' else 'brand_agent'}'
            ) WHERE org_unit_id IS NULL;
        """)

    # mall_orders 全部 mall
    op.execute("""
        UPDATE mall_orders SET org_unit_id = (
            SELECT id FROM org_units WHERE code = 'mall'
        ) WHERE org_unit_id IS NULL;
    """)

    # mall_purchase_orders 按 scope 拆
    op.execute("""
        UPDATE mall_purchase_orders SET org_unit_id = (
            SELECT id FROM org_units WHERE code =
                CASE WHEN mall_purchase_orders.scope = 'store' THEN 'retail' ELSE 'mall' END
        ) WHERE org_unit_id IS NULL;
    """)

    # commissions: 有 mall_order_id 的改回 mall
    op.execute("""
        UPDATE commissions SET org_unit_id = (
            SELECT id FROM org_units WHERE code = 'mall'
        ) WHERE mall_order_id IS NOT NULL;
    """)

    # ------------------------------------------------------------------
    # 4. SET NOT NULL + 索引
    # ------------------------------------------------------------------
    for table_name in ("orders", "commissions", "store_sales", "mall_orders", "mall_purchase_orders"):
        op.alter_column(table_name, "org_unit_id", nullable=False)
        op.create_index(
            f"ix_{table_name}_org_unit_id",
            table_name,
            ["org_unit_id"],
        )


def downgrade():
    for table_name in ("orders", "commissions", "store_sales", "mall_orders", "mall_purchase_orders"):
        op.drop_index(f"ix_{table_name}_org_unit_id", table_name=table_name)
        op.drop_constraint(f"fk_{table_name}_org_unit", table_name, type_="foreignkey")
        op.drop_column(table_name, "org_unit_id")
    op.drop_table("org_units")
