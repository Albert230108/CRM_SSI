"""add onedrive delegated auth columns to admin_settings

Revision ID: 0091_add_onedrive_delegated_auth
Revises: 0090_add_sales_manager_agent
Create Date: 2026-09-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0091_add_onedrive_delegated_auth"
down_revision = "0090_add_sales_manager_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("admin_settings", sa.Column("onedrive_refresh_token_encrypted", sa.Text(), nullable=True))
    op.add_column("admin_settings", sa.Column("onedrive_drive_id", sa.String(length=255), nullable=True))
    op.add_column("admin_settings", sa.Column("onedrive_account_label", sa.String(length=255), nullable=True))
    op.add_column("admin_settings", sa.Column("onedrive_token_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("admin_settings", "onedrive_token_updated_at")
    op.drop_column("admin_settings", "onedrive_account_label")
    op.drop_column("admin_settings", "onedrive_drive_id")
    op.drop_column("admin_settings", "onedrive_refresh_token_encrypted")
