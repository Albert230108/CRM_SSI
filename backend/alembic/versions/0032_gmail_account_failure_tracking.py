"""add gmail_accounts failure tracking columns

Revision ID: 0032_gmail_account_failure_tracking
Revises: 0031_add_thread_ref_to_notifications
Create Date: 2026-07-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0032_gmail_account_failure_tracking"
down_revision = "0031_add_thread_ref_to_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gmail_accounts",
        sa.Column("consecutive_failure_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("gmail_accounts", sa.Column("last_error_message", sa.Text(), nullable=True))
    op.add_column("gmail_accounts", sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("gmail_accounts", "last_failure_at")
    op.drop_column("gmail_accounts", "last_error_message")
    op.drop_column("gmail_accounts", "consecutive_failure_count")
