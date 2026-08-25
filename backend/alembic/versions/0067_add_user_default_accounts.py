"""add default account preferences to users

Revision ID: 0067_add_user_default_accounts
Revises: 0066_add_admin_writer_defaults
Create Date: 2026-08-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0067_add_user_default_accounts'
down_revision = '0066_add_admin_writer_defaults'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('default_gmail_account_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_users_default_gmail_account_id_gmail_accounts',
        'users',
        'gmail_accounts',
        ['default_gmail_account_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.add_column('users', sa.Column('default_whatsapp_account_id', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_constraint('fk_users_default_gmail_account_id_gmail_accounts', 'users', type_='foreignkey')
    op.drop_column('users', 'default_whatsapp_account_id')
    op.drop_column('users', 'default_gmail_account_id')
