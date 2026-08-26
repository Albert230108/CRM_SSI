"""add rich fields to communication reply drafts

Revision ID: 0077_add_rich_fields_to_communication_reply_drafts
Revises: 0076_add_bulk_planner_schedules
Create Date: 2026-08-26 00:00:03.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0077_add_rich_fields_to_communication_reply_drafts"
down_revision = "0076_add_bulk_planner_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "communication_reply_drafts",
        sa.Column("body_html", sa.Text(), nullable=True),
    )
    op.add_column(
        "communication_reply_drafts",
        sa.Column("body_format", sa.String(length=20), nullable=False, server_default="plain"),
    )


def downgrade() -> None:
    op.drop_column("communication_reply_drafts", "body_format")
    op.drop_column("communication_reply_drafts", "body_html")
