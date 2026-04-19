"""add_scheme_no_to_request_item

Revision ID: 1c530b6c97c3
Revises: bdc5aba70595
Create Date: 2026-04-16

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '1c530b6c97c3'
down_revision: Union[str, None] = 'bdc5aba70595'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('policy_request_items', sa.Column('scheme_no', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('policy_request_items', 'scheme_no')
