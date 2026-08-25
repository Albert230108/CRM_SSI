"""add ai auto draft resolution reason

Revision ID: 0063_add_ai_auto_draft_resolution_reason
Revises: 0062_add_action_item_tags_and_todoist_fields
Create Date: 2026-08-25 00:00:00.000002
"""
from alembic import op
import sqlalchemy as sa


revision = "0063_add_ai_auto_draft_resolution_reason"
down_revision = "0062_add_action_item_tags_and_todoist_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_auto_drafts", sa.Column("resolution_reason", sa.Text(), nullable=True))
    op.add_column("ai_auto_drafts", sa.Column("resolution_source", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_auto_drafts", "resolution_source")
    op.drop_column("ai_auto_drafts", "resolution_reason")
