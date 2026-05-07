"""M6c.a: 建 MALL_MASTER + STORE_MASTER 两个独立现金池账户

需求：
  - 商城（mall）和门店（store）采购独立账户
  - 资金从总资金池 master 通过现有 `/api/accounts/transfer` 调拨到这里
  - 采购付款从此账户扣
  - 和品牌事业部现金（level='project', brand_id=X）平行，但 brand_id=null

level 取值扩展：master / project / mall / store

Revision ID: m6caaccts
Revises: m6c9refundedfrom
Create Date: 2026-05-05
"""
from alembic import op


revision = "m6caaccts"
down_revision = "m6c9refundedfrom"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO accounts (id, code, name, account_type, level, brand_id, balance, is_active, notes)
        VALUES
          (gen_random_uuid()::text, 'MALL_MASTER', '商城现金池', 'cash', 'mall',
           NULL, 0, true, '商城采购专用现金池，从 master 调拨入账'),
          (gen_random_uuid()::text, 'STORE_MASTER', '门店现金池', 'cash', 'store',
           NULL, 0, true, '门店采购专用现金池，从 master 调拨入账')
        ON CONFLICT (code) DO NOTHING;
    """)


def downgrade():
    op.execute("DELETE FROM accounts WHERE code IN ('MALL_MASTER', 'STORE_MASTER');")
