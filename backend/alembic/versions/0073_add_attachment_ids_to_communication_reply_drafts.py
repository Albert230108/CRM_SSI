"""add attachment ids to communication reply drafts

Revision ID: 0073_add_attachment_ids_to_communication_reply_drafts
Revises: 0072_add_formatter_default_enabled
Create Date: 2026-08-26 00:00:02.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0073_add_attachment_ids_to_communication_reply_drafts"
down_revision = "0072_add_formatter_default_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "communication_reply_drafts",
        sa.Column("attachment_ids", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("communication_reply_drafts", "attachment_ids")
