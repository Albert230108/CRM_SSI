"""add gmail_accounts.watch_expiration

Revision ID: 0021_gmail_watch_expiration
Revises: 0020_add_password_reset_tokens
Create Date: 2026-07-16 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0021_gmail_watch_expiration"
down_revision = "0020_add_password_reset_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gmail_accounts", sa.Column("watch_expiration", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("gmail_accounts", "watch_expiration")
