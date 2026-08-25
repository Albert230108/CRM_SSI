"""add admin defaults for brain and action writer

Revision ID: 0066_add_admin_writer_defaults
Revises: 0065_add_action_item_tags_join_table
Create Date: 2026-08-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0066_add_admin_writer_defaults'
down_revision = '0065_add_action_item_tags_join_table'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('admin_settings', sa.Column('brain_writer_default_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('admin_settings', sa.Column('action_writer_default_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('admin_settings', 'action_writer_default_enabled')
    op.drop_column('admin_settings', 'brain_writer_default_enabled')
