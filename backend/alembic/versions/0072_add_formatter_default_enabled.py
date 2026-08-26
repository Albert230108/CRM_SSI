"""add formatter default enabled for new tenants

Revision ID: 0072_add_formatter_default_enabled
Revises: 0071_add_formatted_text_to_ai_auto_drafts
Create Date: 2026-08-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0072_add_formatter_default_enabled"
down_revision = "0071_add_formatted_text_to_ai_auto_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admin_settings",
        sa.Column("formatter_default_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("admin_settings", "formatter_default_enabled")
