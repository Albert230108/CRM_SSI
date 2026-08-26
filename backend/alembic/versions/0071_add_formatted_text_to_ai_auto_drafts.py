"""add formatted text to ai auto drafts

Revision ID: 0071_add_formatted_text_to_ai_auto_drafts
Revises: 0070_add_formatter_role_and_settings
Create Date: 2026-08-26 00:00:01.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0071_add_formatted_text_to_ai_auto_drafts"
down_revision = "0070_add_formatter_role_and_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_auto_drafts",
        sa.Column("formatted_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_auto_drafts", "formatted_text")
