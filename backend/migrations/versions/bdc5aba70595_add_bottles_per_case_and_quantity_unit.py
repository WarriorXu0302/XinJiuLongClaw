"""add_bottles_per_case_and_quantity_unit

Revision ID: bdc5aba70595
Revises: 788ba38160bf
Create Date: 2026-04-16 22:24:08.545594

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'bdc5aba70595'
down_revision: Union[str, None] = '788ba38160bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('bottles_per_case', sa.Integer(), server_default='6', nullable=False))
    op.add_column('order_items', sa.Column('quantity_unit', sa.String(length=10), server_default="'瓶'", nullable=False))


def downgrade() -> None:
    op.drop_column('order_items', 'quantity_unit')
    op.drop_column('products', 'bottles_per_case')
