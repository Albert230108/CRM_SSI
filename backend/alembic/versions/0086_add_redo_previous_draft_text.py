"""add previous_draft_text snapshot to redo_request_logs

Revision ID: 0086_add_redo_previous_draft_text
Revises: 0085_add_action_saved_view_layout_grouping
Create Date: 2026-08-31 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0086_add_redo_previous_draft_text"
down_revision = "0085_add_action_saved_view_layout_grouping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("redo_request_logs", sa.Column("previous_draft_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("redo_request_logs", "previous_draft_text")
