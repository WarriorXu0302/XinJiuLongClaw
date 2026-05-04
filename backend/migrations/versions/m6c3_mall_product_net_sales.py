"""M6c.3: mall_products 加 net_sales（净销量，退货时扣）

决策 #4 商品销量双数据：
- total_sales 保持"曾售卖瓶数"语义（含退货），不回退
- 新增 net_sales：净销量（退货时扣），首页榜单优先用它
- 历史数据：初始化 net_sales = total_sales（第一版认为还没退货或可忽略）

Revision ID: m6c3netsales
Revises: m6c2walkin
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa


revision = "m6c3netsales"
down_revision = "m6c2walkin"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "mall_products",
        sa.Column(
            "net_sales", sa.Integer(),
            nullable=False, server_default="0",
        ),
    )
    # 初始化：历史 net_sales = total_sales（认为老数据没有退货记录或不追溯）
    op.execute("UPDATE mall_products SET net_sales = total_sales")
    # 清掉 default，后续靠 ORM 层维护
    op.alter_column("mall_products", "net_sales", server_default=None)


def downgrade():
    op.drop_column("mall_products", "net_sales")
