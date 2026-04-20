"""add feishu_bindings

Revision ID: f17a_feishu_binding
Revises: a1b2c3d4e5f6
Create Date: 2026-04-20
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f17a_feishu_binding'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'feishu_bindings',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('open_id', sa.String(100), nullable=False),
        sa.Column('user_id', sa.String(36),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.text('true')),
        sa.Column('bound_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('unbind_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('open_id', name='uq_feishu_bindings_open_id'),
        sa.UniqueConstraint('user_id', name='uq_feishu_bindings_user_id'),
    )
    op.create_index('ix_feishu_bindings_open_id', 'feishu_bindings', ['open_id'])
    op.create_index('ix_feishu_bindings_user_id', 'feishu_bindings', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_feishu_bindings_user_id', table_name='feishu_bindings')
    op.drop_index('ix_feishu_bindings_open_id', table_name='feishu_bindings')
    op.drop_table('feishu_bindings')
