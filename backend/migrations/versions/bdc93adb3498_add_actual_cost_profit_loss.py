"""add_actual_cost_profit_loss

Revision ID: bdc93adb3498
Revises: 1c530b6c97c3
Create Date: 2026-04-16

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'bdc93adb3498'
down_revision: Union[str, None] = '1c530b6c97c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('policy_request_items', sa.Column('actual_cost', sa.Numeric(precision=15, scale=2), server_default='0', nullable=False))
    op.add_column('policy_request_items', sa.Column('profit_loss', sa.Numeric(precision=15, scale=2), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('policy_request_items', 'profit_loss')
    op.drop_column('policy_request_items', 'actual_cost')
