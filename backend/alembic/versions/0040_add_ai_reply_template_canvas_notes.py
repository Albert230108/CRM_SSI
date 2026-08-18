"""add canvas_notes to ai_reply_templates

Revision ID: 0040_add_ai_reply_template_canvas_notes
Revises: 0039_add_ai_agent_runs
Create Date: 2026-08-18 00:00:03.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0040_add_ai_reply_template_canvas_notes"
down_revision = "0039_add_ai_agent_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_reply_templates",
        sa.Column("canvas_notes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("ai_reply_templates", "canvas_notes")
