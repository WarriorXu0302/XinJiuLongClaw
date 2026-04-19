"""add_order_lifecycle_fields

Revision ID: 788ba38160bf
Revises: d0cc55f309cd
Create Date: 2026-04-16 06:11:38.700067

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '788ba38160bf'
down_revision: Union[str, None] = 'd0cc55f309cd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('notification_logs', sa.Column('read_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('orders', sa.Column('delivery_photos', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('orders', sa.Column('payment_voucher_urls', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'payment_voucher_urls')
    op.drop_column('orders', 'delivery_photos')
    op.drop_column('notification_logs', 'read_at')
