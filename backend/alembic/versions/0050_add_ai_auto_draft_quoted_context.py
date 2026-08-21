"""add ai_auto_drafts.quoted_context

Revision ID: 0050_add_ai_auto_draft_quoted_context
Revises: 0049_add_conversation_link_visibility
Create Date: 2026-08-21 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "0050_add_ai_auto_draft_quoted_context"
down_revision = "0049_add_conversation_link_visibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_auto_drafts", sa.Column("quoted_context", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_auto_drafts", "quoted_context")
